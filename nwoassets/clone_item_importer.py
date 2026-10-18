from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import struct

from .appearance_sheet import split_appearance_sheet
from .atomic import atomic_binary_output
from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import (
    _commit_transaction,
    _remove_if_exists,
    _sha256_segment,
    _transaction_path,
    verify_sprite_hash_algorithm,
)
from .item_xml_clone import clone_xml_definitions
from .otb import OtbNode, inspect_otb, parse_otb_tree
from .otfi import parse_otfi
from .pipeline import inspect_client
from .png import PngImage, normalize_rgba, read_png_rgba, split_tiles_bottom_right_first
from .remake_importer import _assert_map_targets_absent
from .roundtrip import append_spr_blocks, encode_item_appearance, scan_dat_record_spans, write_otb_document
from .sprites import RGBA_SIZE, decode_sprite_rgba, encode_sprite_rgba, read_spr_blocks, sprite_hash
from .versioning import create_version, require_asset_layout


@dataclass(frozen=True)
class CloneItemEntry:
    sequence: int
    source_server_id: int
    target_server_id: int
    target_client_id: int
    source_path: Path
    frame_width: int
    frame_height: int
    frames: int
    frame_duration_ms: int | None
    animation_async: bool
    layers: int = 1
    pattern_x: int = 1
    pattern_y: int = 1
    pattern_z: int = 1


def read_clone_item_manifest(path: Path) -> list[CloneItemEntry]:
    path = path.resolve()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "sequence", "source_server_id", "target_server_id", "target_client_id",
            "source_path", "frame_width", "frame_height", "frames",
            "frame_duration_ms", "animation_async",
        }
        optional = {"layers", "pattern_x", "pattern_y", "pattern_z"}
        received = set(reader.fieldnames or ())
        if not required.issubset(received) or received - required - optional:
            raise FormatError(
                f"{path}: colunas obrigatorias: {sorted(required)}; "
                f"opcionais: {sorted(optional)}"
            )
        entries: list[CloneItemEntry] = []
        for row_number, row in enumerate(reader, 2):
            try:
                sequence = int(row["sequence"])
                source_server_id = int(row["source_server_id"])
                target_server_id = int(row["target_server_id"])
                target_client_id = int(row["target_client_id"])
                frame_width = int(row["frame_width"])
                frame_height = int(row["frame_height"])
                frames = int(row["frames"])
                layers = int((row.get("layers") or "1").strip())
                pattern_x = int((row.get("pattern_x") or "1").strip())
                pattern_y = int((row.get("pattern_y") or "1").strip())
                pattern_z = int((row.get("pattern_z") or "1").strip())
            except (TypeError, ValueError) as exc:
                raise FormatError(f"{path}:{row_number}: valor numerico invalido") from exc
            duration_raw = (row["frame_duration_ms"] or "").strip()
            try:
                duration = int(duration_raw) if duration_raw else None
            except ValueError as exc:
                raise FormatError(f"{path}:{row_number}: duracao invalida") from exc
            async_raw = (row["animation_async"] or "0").strip()
            if async_raw not in {"0", "1"}:
                raise FormatError(f"{path}:{row_number}: animation_async deve ser 0 ou 1")
            if min(source_server_id, target_server_id, target_client_id) < 1:
                raise FormatError(f"{path}:{row_number}: IDs devem ser positivos")
            if frame_width % 32 or frame_height % 32 or min(frame_width, frame_height) < 32:
                raise FormatError(f"{path}:{row_number}: frame deve ser multiplo de 32")
            if frame_width // 32 > 255 or frame_height // 32 > 255:
                raise FormatError(f"{path}:{row_number}: frame excede 255 tiles")
            if not 1 <= frames <= 255:
                raise FormatError(f"{path}:{row_number}: frames deve estar em 1..255")
            if any(value < 1 or value > 255 for value in (
                layers, pattern_x, pattern_y, pattern_z
            )):
                raise FormatError(f"{path}:{row_number}: layers/patterns devem estar em 1..255")
            if frames > 1 and (duration is None or duration < 1):
                raise FormatError(f"{path}:{row_number}: animacao exige duracao positiva")
            if frames == 1 and (duration is not None or async_raw == "1"):
                raise FormatError(f"{path}:{row_number}: item estatico nao aceita duracao/async")
            source = Path(row["source_path"])
            if not source.is_absolute():
                source = path.parent / source
            source = source.resolve()
            if source.suffix.casefold() != ".png" or not source.is_file():
                raise FormatError(f"{path}:{row_number}: PNG ausente: {source}")
            entries.append(CloneItemEntry(
                sequence, source_server_id, target_server_id, target_client_id,
                source, frame_width, frame_height, frames, duration, async_raw == "1",
                layers, pattern_x, pattern_y, pattern_z,
            ))
    if not entries or [e.sequence for e in entries] != list(range(1, len(entries) + 1)):
        raise FormatError(f"{path}: sequence deve ser continua a partir de 1")
    # Uma mesma referencia pode originar varios itens novos. Somente os
    # destinos e os arquivos de aparencia precisam ser exclusivos no lote.
    for field in ("target_server_id", "target_client_id", "source_path"):
        values = [getattr(entry, field) for entry in entries]
        if len(values) != len(set(values)):
            raise FormatError(f"{path}: {field} duplicado")
    return entries


def split_frame_grid(
    image: PngImage, frame_width: int, frame_height: int, frames: int
) -> tuple[tuple[bytes, ...], ...]:
    if image.width % frame_width or image.height % frame_height:
        raise FormatError(
            f"imagem {image.width}x{image.height} nao fecha grade "
            f"{frame_width}x{frame_height}"
        )
    columns = image.width // frame_width
    rows = image.height // frame_height
    if columns * rows != frames:
        raise FormatError(
            f"grade contem {columns * rows} frames; manifesto declara {frames}"
        )
    groups: list[tuple[bytes, ...]] = []
    source_stride = image.width * 4
    for row in range(rows):
        for column in range(columns):
            rgba = bytearray(frame_width * frame_height * 4)
            destination_stride = frame_width * 4
            for y in range(frame_height):
                source_start = (
                    (row * frame_height + y) * source_stride + column * destination_stride
                )
                target_start = y * destination_stride
                rgba[target_start : target_start + destination_stride] = image.rgba[
                    source_start : source_start + destination_stride
                ]
            frame = PngImage(frame_width, frame_height, bytes(rgba))
            groups.append(tuple(split_tiles_bottom_right_first(frame, 32)))
    return tuple(groups)


def _otb_node_ids(node: OtbNode, source: str) -> tuple[int | None, int | None]:
    position = 5
    server_id = client_id = None
    while position < len(node.data):
        if position + 3 > len(node.data):
            raise FormatError(f"{source}: atributo OTB truncado")
        attribute = node.data[position]
        length = struct.unpack_from("<H", node.data, position + 1)[0]
        position += 3
        if position + length > len(node.data):
            raise FormatError(f"{source}: payload OTB truncado")
        if attribute in {0x10, 0x11}:
            if length != 2:
                raise FormatError(f"{source}: ID OTB com tamanho invalido")
            value = struct.unpack_from("<H", node.data, position)[0]
            if attribute == 0x10:
                server_id = value
            else:
                client_id = value
        position += length
    return server_id, client_id


def clone_otb_node(
    source: OtbNode, *, server_id: int, client_id: int, digest: bytes, animated: bool
) -> OtbNode:
    if source.children:
        raise FormatError("item OTB de referencia possui filhos")
    if len(source.data) < 5 or len(digest) != 16:
        raise FormatError("no OTB de referencia ou SpriteHash invalido")
    output = bytearray(source.data[:5])
    flags = struct.unpack_from("<I", output, 1)[0]
    animation_bit = 1 << 24
    flags = flags | animation_bit if animated else flags & ~animation_bit
    struct.pack_into("<I", output, 1, flags)
    position = 5
    found: set[int] = set()
    while position < len(source.data):
        attribute = source.data[position]
        length = struct.unpack_from("<H", source.data, position + 1)[0]
        position += 3
        payload = source.data[position : position + length]
        position += length
        if attribute == 0x10:
            payload = struct.pack("<H", server_id)
            found.add(attribute)
        elif attribute == 0x11:
            payload = struct.pack("<H", client_id)
            found.add(attribute)
        elif attribute == 0x20:
            payload = digest
            found.add(attribute)
        output.append(attribute)
        output.extend(struct.pack("<H", len(payload)))
        output.extend(payload)
    for attribute, payload in (
        (0x10, struct.pack("<H", server_id)),
        (0x11, struct.pack("<H", client_id)),
        (0x20, digest),
    ):
        if attribute not in found:
            output.append(attribute)
            output.extend(struct.pack("<H", len(payload)))
            output.extend(payload)
    return OtbNode(bytes(output), [])


def write_dat_with_clones(
    source: Path, destination: Path, otfi, records: list[bytes]
) -> None:
    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("destino DAT temporario invalido")
    data = source.read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(source))
    item_spans = [span for span in spans if span.category == "items"]
    if not item_spans:
        raise FormatError("DAT nao possui items")
    old_max = struct.unpack_from("<H", data, 4)[0]
    if item_spans[-1].thing_id != old_max:
        raise FormatError("max item ID do DAT diverge da arvore")
    new_max = old_max + len(records)
    if new_max > 0xFFFF:
        raise FormatError("novos Client IDs excedem uint16")
    boundary = item_spans[-1].end
    header = bytearray(data[:12])
    struct.pack_into("<H", header, 4, new_max)
    with atomic_binary_output(destination) as output:
        output.write(header)
        output.write(data[12:boundary])
        for record in records:
            output.write(record)
        output.write(data[boundary:])


def write_otb_with_clones(
    source: Path, destination: Path, nodes: list[OtbNode]
) -> None:
    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("destino OTB temporario invalido")
    version, root = parse_otb_tree(source)
    write_otb_document(version, OtbNode(root.data, [*root.children, *nodes]), destination)


def import_cloned_items(
    root: Path, manifest_path: Path, *, deep_spr: bool = True, dry_run: bool = False
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    layout = require_asset_layout(root)
    entries = read_clone_item_manifest(manifest_path)
    sprites_root = (root / "sprites").resolve()
    if not all(entry.source_path.is_relative_to(sprites_root) for entry in entries):
        raise FormatError("PNGs devem estar em NWO-ASSETS/sprites")
    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline reprovada: {baseline['errors']}")
    paths = {name: Path(value) for name, value in baseline["paths"].items()}
    paths["xml"] = layout["items"] / "items.xml"
    otfi = parse_otfi(paths["otfi"])
    if not (otfi.extended and otfi.transparency and otfi.frame_durations):
        raise FormatError("perfil OTFI nao suporta o importador de clones")
    hash_gate = verify_sprite_hash_algorithm(paths["dat"], paths["spr"], paths["otb"], otfi)
    if not hash_gate["passed"]:
        raise FormatError("SpriteHash da baseline diverge")

    source_data = paths["dat"].read_bytes()
    source_spans = scan_dat_record_spans(source_data, otfi, str(paths["dat"]))
    dat_items = {span.thing_id: span for span in source_spans if span.category == "items"}
    old_client_max = max(dat_items)
    if [entry.target_client_id for entry in entries] != list(
        range(old_client_max + 1, old_client_max + len(entries) + 1)
    ):
        raise FormatError("target_client_id deve continuar o DAT sem lacunas")
    otb_version, otb_root = parse_otb_tree(paths["otb"])
    del otb_version
    source_nodes: dict[int, OtbNode] = {}
    existing_server_ids: list[int] = []
    for index, node in enumerate(otb_root.children):
        server_id, client_id = _otb_node_ids(node, f"{paths['otb']}:item-{index}")
        if server_id is None or client_id is None:
            continue
        if server_id in source_nodes:
            raise FormatError(f"Server ID OTB duplicado: {server_id}")
        source_nodes[server_id] = node
        existing_server_ids.append(server_id)
    old_server_max = max(existing_server_ids)
    if [entry.target_server_id for entry in entries] != list(
        range(old_server_max + 1, old_server_max + len(entries) + 1)
    ):
        raise FormatError("target_server_id deve continuar o OTB sem lacunas")

    old_sprite_count = int(baseline["spr"]["sprite_count"])
    next_sprite_id = old_sprite_count + 1
    blank = bytes(RGBA_SIZE)
    blocks: list[bytes] = []
    expected_tiles: dict[int, bytes] = {}
    records: list[bytes] = []
    new_nodes: list[OtbNode] = []
    reports: list[dict[str, object]] = []
    for entry in entries:
        source_node = source_nodes.get(entry.source_server_id)
        if source_node is None:
            raise FormatError(f"Server ID de referencia ausente: {entry.source_server_id}")
        _, source_client_id = _otb_node_ids(source_node, str(paths["otb"]))
        if source_client_id not in dat_items:
            raise FormatError(f"referencia {entry.source_server_id} aponta para DAT inexistente")
        image = normalize_rgba(read_png_rgba(
            entry.source_path,
            max_width=entry.frame_width * entry.layers * entry.pattern_x,
            max_height=(
                entry.frame_height * entry.frames * entry.pattern_y * entry.pattern_z
            ),
        ))
        groups = split_appearance_sheet(
            image,
            sprite_size=otfi.sprite_size,
            width=entry.frame_width // otfi.sprite_size,
            height=entry.frame_height // otfi.sprite_size,
            layers=entry.layers,
            pattern_x=entry.pattern_x,
            pattern_y=entry.pattern_y,
            pattern_z=entry.pattern_z,
            frames=entry.frames,
        )
        sprite_ids: list[int] = []
        for group in groups:
            for tile in group:
                if tile == blank:
                    sprite_ids.append(0)
                else:
                    sprite_ids.append(next_sprite_id)
                    expected_tiles[next_sprite_id] = tile
                    blocks.append(encode_sprite_rgba(tile))
                    next_sprite_id += 1
        source_appearance = dat_items[source_client_id].appearances[0]
        exact_size = None
        width_tiles = entry.frame_width // 32
        height_tiles = entry.frame_height // 32
        if width_tiles > 1 or height_tiles > 1:
            exact_size = source_appearance.exact_size or 32
        appearance = encode_item_appearance(
            width_tiles,
            height_tiles,
            entry.frames,
            tuple(sprite_ids),
            otfi,
            frame_duration_ms=entry.frame_duration_ms,
            animation_async=entry.animation_async,
            exact_size=exact_size,
            allow_zero_sprite_ids=True,
            layers=entry.layers,
            pattern_x=entry.pattern_x,
            pattern_y=entry.pattern_y,
            pattern_z=entry.pattern_z,
        )
        properties = source_data[
            dat_items[source_client_id].start : dat_items[source_client_id].properties_end
        ]
        records.append(properties + appearance)
        digest = sprite_hash([
            tile for group in groups[:entry.layers] for tile in group
        ])
        new_nodes.append(clone_otb_node(
            source_node,
            server_id=entry.target_server_id,
            client_id=entry.target_client_id,
            digest=digest,
            animated=entry.frames > 1,
        ))
        reports.append({
            "sequence": entry.sequence,
            "source_server_id": entry.source_server_id,
            "source_client_id": source_client_id,
            "target_server_id": entry.target_server_id,
            "target_client_id": entry.target_client_id,
            "source_path": str(entry.source_path),
            "source_sha256": sha256_file(entry.source_path),
            "image_size": [image.width, image.height],
            "frame_size": [entry.frame_width, entry.frame_height],
            "frames": entry.frames,
            "layers": entry.layers,
            "pattern_x": entry.pattern_x,
            "pattern_y": entry.pattern_y,
            "pattern_z": entry.pattern_z,
            "frame_duration_ms": entry.frame_duration_ms,
            "animation_async": entry.animation_async,
            "sprite_id_count": sum(1 for value in sprite_ids if value),
            "sprite_id_range": (
                [min(value for value in sprite_ids if value), max(value for value in sprite_ids if value)]
                if any(sprite_ids) else []
            ),
            "sprite_hash": digest.hex().upper(),
        })

    maps = sorted(layout["world"].glob("*.otbm"))
    if len(maps) != 1:
        raise FormatError("esperado exatamente um mapa canonico")
    map_scan = _assert_map_targets_absent(
        maps[0], {entry.target_server_id for entry in entries}
    )
    original_xml = paths["xml"].read_bytes()
    prepared_xml, xml_report = clone_xml_definitions(
        original_xml,
        {entry.target_server_id: entry.source_server_id for entry in entries},
    )
    protected = {
        path: sha256_file(path)
        for path in (root / "assets").rglob("*")
        if path.is_file()
    }
    source_png_hashes = {str(e.source_path): sha256_file(e.source_path) for e in entries}
    common = {
        "root": str(root),
        "manifest": str(manifest_path),
        "item_count": len(entries),
        "target_server_id_range": [entries[0].target_server_id, entries[-1].target_server_id],
        "target_client_id_range": [entries[0].target_client_id, entries[-1].target_client_id],
        "new_sprite_count": len(blocks),
        "sprite_id_range": [old_sprite_count + 1, next_sprite_id - 1],
        "items": reports,
        "xml": xml_report,
        "map_scan": map_scan,
    }
    if dry_run:
        return {**common, "dry_run": True, "passed": True}

    pending = {
        name: _transaction_path(paths[name], "pending")
        for name in ("dat", "spr", "otb", "xml")
    }
    if any(path.exists() for path in pending.values()):
        raise FormatError("arquivos temporarios de importacao ja existem")
    backup = create_version(root)
    try:
        append_spr_blocks(paths["spr"], pending["spr"], otfi, blocks)
        write_dat_with_clones(paths["dat"], pending["dat"], otfi, records)
        write_otb_with_clones(paths["otb"], pending["otb"], new_nodes)
        with atomic_binary_output(pending["xml"]) as stream:
            stream.write(prepared_xml)
        pending_spr = inspect_spr(pending["spr"], otfi, deep=deep_spr)
        pending_dat = inspect_dat(
            pending["dat"], otfi,
            expected_metadata_reader=int(baseline["profile"]["metadata_reader"]),
            sprite_count=int(pending_spr["sprite_count"]),
        )
        pending_otb = inspect_otb(pending["otb"])
        if pending_otb["malformed_attributes"]:
            raise FormatError("OTB preparado possui atributos malformados")
        if int(pending_spr["sprite_count"]) != next_sprite_id - 1:
            raise FormatError("contagem SPR preparada diverge")
        if int(pending_dat["max_ids"]["items"]) != entries[-1].target_client_id:
            raise FormatError("max item ID DAT preparado diverge")
        staged_data = pending["dat"].read_bytes()
        staged_spans = scan_dat_record_spans(staged_data, otfi, str(pending["dat"]))
        staged_by_key = {(s.category, s.thing_id): s for s in staged_spans}
        for span in source_spans:
            staged = staged_by_key[(span.category, span.thing_id)]
            if source_data[span.start:span.end] != staged_data[staged.start:staged.end]:
                raise FormatError(f"registro DAT antigo mudou: {span.category} {span.thing_id}")
        for entry, record in zip(entries, records):
            span = staged_by_key[("items", entry.target_client_id)]
            if staged_data[span.start:span.end] != record:
                raise FormatError(f"Client ID novo nao persistiu: {entry.target_client_id}")
        _, staged_otb = parse_otb_tree(pending["otb"])
        if len(staged_otb.children) != len(otb_root.children) + len(new_nodes):
            raise FormatError("quantidade de nos OTB preparada diverge")
        for before, after in zip(otb_root.children, staged_otb.children):
            if before.data != after.data or before.children != after.children:
                raise FormatError("no OTB antigo mudou")
        for expected, actual in zip(new_nodes, staged_otb.children[len(otb_root.children):]):
            if expected.data != actual.data or actual.children:
                raise FormatError("no OTB novo nao persistiu")
        if pending["xml"].read_bytes() != prepared_xml:
            raise FormatError("items.xml preparado nao persistiu")
        old_body_start = int(baseline["spr"]["table_end"])
        new_body_start = int(pending_spr["table_end"])
        old_body_size = paths["spr"].stat().st_size - old_body_start
        if _sha256_segment(paths["spr"], old_body_start) != _sha256_segment(
            pending["spr"], new_body_start, old_body_size
        ):
            raise FormatError("payload dos sprites antigos mudou")
        written = read_spr_blocks(pending["spr"], set(expected_tiles), otfi)
        for sprite_id, expected in expected_tiles.items():
            if decode_sprite_rgba(written[sprite_id], transparency=True) != expected:
                raise FormatError(f"Sprite ID {sprite_id}: pixels divergentes")
        if protected != {
            path: sha256_file(path) for path in protected
        }:
            raise FormatError("baseline mudou durante a preparacao")
        if source_png_hashes != {
            str(e.source_path): sha256_file(e.source_path) for e in entries
        }:
            raise FormatError("PNG de origem mudou durante a preparacao")
        final = _commit_transaction(
            root,
            {paths[name]: pending[name] for name in ("dat", "spr", "otb", "xml")},
            deep_spr=deep_spr,
        )
    except BaseException:
        _remove_if_exists(list(pending.values()))
        raise
    for path, digest in protected.items():
        if path not in {paths["dat"], paths["spr"], paths["otb"], paths["xml"]} and sha256_file(path) != digest:
            raise FormatError(f"asset fora do lote mudou: {path}")
    return {
        **common,
        "version_backup": backup,
        "transaction_committed": True,
        "old_dat_records_preserved": True,
        "old_otb_nodes_preserved": True,
        "old_sprite_payload_preserved": True,
        "new_sprite_pixels_verified": True,
        "final_validation_passed": final["passed"],
        "warnings": final["warnings"],
        "errors": [],
        "passed": True,
    }
