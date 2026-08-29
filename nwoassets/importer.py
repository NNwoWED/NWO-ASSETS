from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import csv
import hashlib
import os
import struct

from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .otb import OtbNode, inspect_otb, parse_otb_tree
from .otfi import OtfiConfig, parse_otfi
from .pipeline import inspect_client, validate_root
from .png import normalize_rgba, read_png_rgba, split_tiles_bottom_right_first
from .roundtrip import (
    append_spr_blocks,
    encode_simple_item_appearance,
    scan_dat_record_spans,
    write_dat_item_appearances,
    write_otb_document,
)
from .sprites import (
    RGBA_SIZE,
    decode_sprite_rgba,
    decode_sprite_for_hash,
    encode_sprite_rgba,
    read_spr_blocks,
    sprite_hash,
)
from .versioning import create_version, require_asset_layout


@dataclass(frozen=True)
class ManifestEntry:
    sequence: int
    client_id: int
    source_path: Path


@dataclass(frozen=True)
class PreparedItem:
    sequence: int
    client_id: int
    source_path: str
    file_sha256: str
    pixels_sha256: str
    image_width: int
    image_height: int
    width_tiles: int
    height_tiles: int
    sprite_ids: tuple[int, ...]
    sprite_hash: str


def read_manifest(path: Path) -> list[ManifestEntry]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"sequence", "client_id", "source_path"}
            missing = required - set(reader.fieldnames or ())
            if missing:
                raise FormatError(
                    f"{path}: colunas ausentes no manifesto: {', '.join(sorted(missing))}"
                )
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FormatError(f"{path}: não foi possível ler o manifesto: {exc}") from exc
    if not rows:
        raise FormatError(f"{path}: manifesto vazio")

    entries: list[ManifestEntry] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            sequence = int(row["sequence"])
            client_id = int(row["client_id"])
        except (TypeError, ValueError) as exc:
            raise FormatError(f"{path}:{row_number}: sequence/client_id inválido") from exc
        raw_source = (row.get("source_path") or "").strip()
        if not raw_source:
            raise FormatError(f"{path}:{row_number}: source_path vazio")
        source = Path(raw_source)
        if not source.is_absolute():
            source = path.parent / source
        source = source.resolve()
        if source.suffix.casefold() != ".png" or not source.is_file():
            raise FormatError(f"{path}:{row_number}: PNG não encontrado: {source}")
        entries.append(ManifestEntry(sequence, client_id, source))

    expected_sequences = list(range(1, len(entries) + 1))
    sequences = [entry.sequence for entry in entries]
    if sequences != expected_sequences:
        raise FormatError(
            f"{path}: sequence deve ser contínua e ordenada: esperado "
            f"{expected_sequences}, recebido {sequences}"
        )
    client_ids = [entry.client_id for entry in entries]
    if len(set(client_ids)) != len(client_ids):
        raise FormatError(f"{path}: Client IDs duplicados")
    sources = [str(entry.source_path).casefold() for entry in entries]
    if len(set(sources)) != len(sources):
        raise FormatError(f"{path}: caminhos PNG duplicados")
    return entries


def _parse_otb_attributes(node: OtbNode, source: str) -> tuple[int | None, list[tuple[int, bytes]]]:
    if len(node.data) < 5:
        raise FormatError(f"{source}: nó OTB curto demais")
    position = 5
    attributes: list[tuple[int, bytes]] = []
    client_id: int | None = None
    while position < len(node.data):
        if position + 3 > len(node.data):
            raise FormatError(f"{source}: atributo OTB truncado")
        attribute = node.data[position]
        length = struct.unpack_from("<H", node.data, position + 1)[0]
        position += 3
        if position + length > len(node.data):
            raise FormatError(f"{source}: payload OTB truncado")
        payload = node.data[position : position + length]
        position += length
        attributes.append((attribute, payload))
        if attribute == 0x11:
            if length != 2:
                raise FormatError(f"{source}: Client ID OTB com tamanho {length}")
            client_id = struct.unpack("<H", payload)[0]
    return client_id, attributes


def _otb_sprite_hashes(path: Path) -> dict[int, list[bytes]]:
    _file_version, root = parse_otb_tree(path)
    result: dict[int, list[bytes]] = {}
    for index, node in enumerate(root.children):
        client_id, attributes = _parse_otb_attributes(node, f"{path}:nó-{index}")
        if client_id is None:
            continue
        hashes = [payload for attribute, payload in attributes if attribute == 0x20]
        if hashes:
            if any(len(value) != 16 for value in hashes):
                raise FormatError(f"{path}: SpriteHash inválido no Client ID {client_id}")
            result.setdefault(client_id, []).extend(hashes)
    return result


def update_otb_sprite_hashes(
    source: Path,
    destination: Path,
    replacements: dict[int, bytes],
) -> dict[int, int]:
    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("OTB de destino deve ser novo e diferente da origem")
    if any(len(value) != 16 for value in replacements.values()):
        raise FormatError("todo SpriteHash deve possuir 16 bytes")
    file_version, root = parse_otb_tree(source)
    original_root_data = root.data
    original_nodes = tuple((node.data, node.children) for node in root.children)
    expected_node_data: dict[int, bytes] = {}
    updated = {client_id: 0 for client_id in replacements}
    for index, node in enumerate(root.children):
        client_id, attributes = _parse_otb_attributes(node, f"{source}:nó-{index}")
        if client_id not in replacements:
            continue
        rebuilt = bytearray(node.data[:5])
        found_hash = False
        for attribute, payload in attributes:
            if attribute == 0x20:
                payload = replacements[client_id]
                found_hash = True
            rebuilt.append(attribute)
            rebuilt.extend(struct.pack("<H", len(payload)))
            rebuilt.extend(payload)
        if not found_hash:
            rebuilt.append(0x20)
            rebuilt.extend(struct.pack("<H", 16))
            rebuilt.extend(replacements[client_id])
        node.data = bytes(rebuilt)
        expected_node_data[index] = node.data
        updated[client_id] += 1
    missing = sorted(client_id for client_id, count in updated.items() if count == 0)
    if missing:
        raise FormatError(f"Client IDs não mapeados no OTB: {missing}")
    write_otb_document(file_version, root, destination)
    written_version, written_root = parse_otb_tree(destination)
    if written_version != file_version or written_root.data != original_root_data:
        raise FormatError("header/root OTB mudou durante a importação")
    if len(written_root.children) != len(original_nodes):
        raise FormatError("quantidade de nós OTB mudou durante a importação")
    for index, (written_node, (original_data, original_children)) in enumerate(
        zip(written_root.children, original_nodes)
    ):
        expected_data = expected_node_data.get(index, original_data)
        if written_node.data != expected_data or written_node.children != original_children:
            raise FormatError(f"nó OTB {index} sofreu alteração fora do escopo")
    written = _otb_sprite_hashes(destination)
    for client_id, expected in replacements.items():
        if not written.get(client_id) or any(value != expected for value in written[client_id]):
            raise FormatError(f"SpriteHash OTB não persistiu para Client ID {client_id}")
    return updated


def verify_sprite_hash_algorithm(
    dat_path: Path,
    spr_path: Path,
    otb_path: Path,
    otfi: OtfiConfig,
    *,
    sample_limit: int = 64,
) -> dict[str, object]:
    data = dat_path.read_bytes()
    items = {
        span.thing_id: span
        for span in scan_dat_record_spans(data, otfi, str(dat_path))
        if span.category == "items"
    }
    otb_hashes = _otb_sprite_hashes(otb_path)
    candidates = sorted(set(items) & set(otb_hashes))
    if not candidates:
        raise FormatError("não há hashes OTB disponíveis para validar o algoritmo")
    if len(candidates) > sample_limit:
        indices = {
            round(index * (len(candidates) - 1) / (sample_limit - 1))
            for index in range(sample_limit)
        }
        candidates = [candidates[index] for index in sorted(indices)]

    sprite_ids: set[int] = set()
    selected: dict[int, tuple[int, ...]] = {}
    for client_id in candidates:
        appearance = items[client_id].appearances[0]
        count = appearance.width * appearance.height * appearance.layers
        selected[client_id] = appearance.sprite_ids[:count]
        sprite_ids.update(sprite_id for sprite_id in selected[client_id] if sprite_id)
    blocks = read_spr_blocks(spr_path, sprite_ids, otfi)
    blank = bytes(RGBA_SIZE)
    mismatches: list[dict[str, object]] = []
    for client_id, ids in selected.items():
        tiles = [
            blank
            if sprite_id == 0
            else decode_sprite_for_hash(blocks[sprite_id], transparency=otfi.transparency)
            for sprite_id in ids
        ]
        calculated = sprite_hash(tiles)
        expected_values = otb_hashes[client_id]
        if any(value != calculated for value in expected_values):
            mismatches.append(
                {
                    "client_id": client_id,
                    "calculated": calculated.hex().upper(),
                    "expected": [value.hex().upper() for value in expected_values],
                }
            )
    return {
        "sample_count": len(candidates),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
        "passed": not mismatches,
    }


def _sha256_segment(path: Path, start: int, length: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = length
    with path.open("rb") as stream:
        stream.seek(start)
        while remaining is None or remaining > 0:
            request = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            chunk = stream.read(request)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    if remaining not in (None, 0):
        raise FormatError(f"{path}: segmento solicitado ultrapassa o fim do arquivo")
    return digest.hexdigest().upper()


def _transaction_path(path: Path, kind: str) -> Path:
    return path.with_name(f".{path.name}.nwoassets.{kind}")


def _remove_if_exists(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _commit_transaction(
    root: Path,
    replacements: dict[Path, Path],
    *,
    deep_spr: bool,
) -> dict[str, object]:
    rollback = {original: _transaction_path(original, "rollback") for original in replacements}
    conflicts = [str(path) for path in rollback.values() if path.exists()]
    if conflicts:
        raise FormatError(f"arquivos de rollback já existem: {conflicts}")

    moved: list[Path] = []
    try:
        for original in replacements:
            os.replace(original, rollback[original])
            moved.append(original)
        for original, pending in replacements.items():
            os.replace(pending, original)
        final_report = validate_root(root, deep_spr=deep_spr)
        if not final_report["passed"]:
            raise FormatError(
                f"validação final reprovou; alterações revertidas: "
                f"{final_report['errors']}"
            )
    except BaseException as original_error:
        restoration_errors: list[str] = []
        for original in reversed(moved):
            old = rollback[original]
            if old.exists():
                try:
                    os.replace(old, original)
                except OSError as exc:
                    restoration_errors.append(f"{original}: {exc}")
        _remove_if_exists(list(replacements.values()))
        if restoration_errors:
            raise FormatError(
                "falha crítica ao restaurar arquivos após erro: "
                + "; ".join(restoration_errors)
            ) from original_error
        raise
    else:
        _remove_if_exists(list(rollback.values()))
        return final_report


def _import_items_impl(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    layout = require_asset_layout(root)
    entries = read_manifest(manifest_path)
    source_report = inspect_client(root, deep_spr=deep_spr)
    if not source_report["passed"]:
        raise FormatError(f"baseline de origem reprovou: {source_report['errors']}")
    paths = {name: Path(value) for name, value in source_report["paths"].items()}
    maps = sorted(layout["world"].glob("*.otbm"))
    if len(maps) != 1:
        raise FormatError(f"esperado um mapa canônico; encontrados {len(maps)}")
    protected_sources = {**paths, "otbm": maps[0]}
    protected_untouched = {
        "otfi": paths["otfi"],
        "otbm": maps[0],
        **{
            f"xml:{path.relative_to(root).as_posix()}": path
            for path in sorted((root / "assets").rglob("*.xml"))
        },
        **{
            f"otml:{path.relative_to(root).as_posix()}": path
            for path in sorted(root.glob("*.otml"))
        },
    }
    source_hashes_before = {
        name: sha256_file(path) for name, path in protected_sources.items()
    }
    otfi = parse_otfi(paths["otfi"])
    if not (otfi.extended and otfi.transparency and otfi.frame_durations and otfi.frame_groups):
        raise FormatError("importador exige as quatro features OTFI da baseline")
    max_item_id = int(source_report["dat"]["max_ids"]["items"])
    invalid_ids = sorted(
        entry.client_id for entry in entries if entry.client_id < 100 or entry.client_id > max_item_id
    )
    if invalid_ids:
        raise FormatError(
            f"esta fase importa somente em Client IDs existentes 100..{max_item_id}: {invalid_ids}"
        )

    hash_gate = verify_sprite_hash_algorithm(paths["dat"], paths["spr"], paths["otb"], otfi)
    if not hash_gate["passed"]:
        raise FormatError(
            "algoritmo SpriteHash não coincide com a baseline: "
            f"{hash_gate['mismatches'][:3]}"
        )

    old_sprite_count = int(source_report["spr"]["sprite_count"])
    next_sprite_id = old_sprite_count + 1
    blocks: list[bytes] = []
    expected_tiles: dict[int, bytes] = {}
    appearances: dict[int, bytes] = {}
    hashes: dict[int, bytes] = {}
    prepared: list[PreparedItem] = []
    for entry in entries:
        image = normalize_rgba(read_png_rgba(entry.source_path))
        tiles = split_tiles_bottom_right_first(image, otfi.sprite_size)
        sprite_ids = tuple(range(next_sprite_id, next_sprite_id + len(tiles)))
        next_sprite_id += len(tiles)
        blocks.extend(encode_sprite_rgba(tile) for tile in tiles)
        expected_tiles.update(zip(sprite_ids, tiles))
        width_tiles = image.width // otfi.sprite_size
        height_tiles = image.height // otfi.sprite_size
        appearances[entry.client_id] = encode_simple_item_appearance(
            width_tiles, height_tiles, sprite_ids, otfi
        )
        item_hash = sprite_hash(tiles)
        hashes[entry.client_id] = item_hash
        prepared.append(
            PreparedItem(
                sequence=entry.sequence,
                client_id=entry.client_id,
                source_path=str(entry.source_path),
                file_sha256=sha256_file(entry.source_path),
                pixels_sha256=hashlib.sha256(image.rgba).hexdigest().upper(),
                image_width=image.width,
                image_height=image.height,
                width_tiles=width_tiles,
                height_tiles=height_tiles,
                sprite_ids=sprite_ids,
                sprite_hash=item_hash.hex().upper(),
            )
        )

    targets = {
        name: _transaction_path(paths[name], "pending")
        for name in ("dat", "spr", "otb")
    }
    stale = [str(path) for path in targets.values() if path.exists()]
    if stale:
        raise FormatError(f"arquivos temporários de importação já existem: {stale}")
    backup = create_version(root)

    def abort_pending(message: str) -> None:
        _remove_if_exists(list(targets.values()))
        raise FormatError(message)

    try:
        append_spr_blocks(paths["spr"], targets["spr"], otfi, blocks)
        write_dat_item_appearances(paths["dat"], targets["dat"], otfi, appearances)
        otb_updates = update_otb_sprite_hashes(paths["otb"], targets["otb"], hashes)

        pending_spr = inspect_spr(targets["spr"], otfi, deep=deep_spr)
        pending_dat = inspect_dat(
            targets["dat"],
            otfi,
            expected_metadata_reader=int(source_report["profile"]["metadata_reader"]),
            sprite_count=int(pending_spr["sprite_count"]),
        )
        pending_otb = inspect_otb(targets["otb"])
        if pending_otb["malformed_attributes"]:
            raise FormatError("OTB preparado possui atributos malformados")
    except BaseException:
        _remove_if_exists(list(targets.values()))
        raise

    expected_sprite_count = old_sprite_count + len(blocks)
    if int(pending_spr["sprite_count"]) != expected_sprite_count:
        abort_pending("count SPR preparado diverge do lote")
    if int(pending_dat["appearance"]["max_referenced_sprite_id"]) > expected_sprite_count:
        abort_pending("DAT preparado referencia Sprite ID fora do novo SPR")

    source_spr_table_end = int(source_report["spr"]["table_end"])
    staged_spr_table_end = int(pending_spr["table_end"])
    old_sprite_body_size = paths["spr"].stat().st_size - source_spr_table_end
    source_sprite_body_hash = _sha256_segment(paths["spr"], source_spr_table_end)
    staged_old_sprite_body_hash = _sha256_segment(
        targets["spr"], staged_spr_table_end, old_sprite_body_size
    )
    if source_sprite_body_hash != staged_old_sprite_body_hash:
        abort_pending("payload dos sprites antigos mudou durante a importação")

    staged_data = targets["dat"].read_bytes()
    source_data = paths["dat"].read_bytes()
    source_spans = scan_dat_record_spans(source_data, otfi, str(paths["dat"]))
    if source_data[:12] != staged_data[:12]:
        abort_pending("header DAT foi alterado durante a importação")
    staged_items = {
        span.thing_id: span
        for span in scan_dat_record_spans(staged_data, otfi, str(targets["dat"]))
        if span.category == "items"
    }
    staged_spans = scan_dat_record_spans(staged_data, otfi, str(targets["dat"]))
    if len(source_spans) != len(staged_spans):
        abort_pending("quantidade de registros DAT mudou durante a importação")
    for source_span, staged_span in zip(source_spans, staged_spans):
        identity = (source_span.category, source_span.thing_id)
        if identity != (staged_span.category, staged_span.thing_id):
            abort_pending("ordem de registros DAT mudou durante a importação")
        source_prefix = source_data[source_span.start : source_span.properties_end]
        staged_prefix = staged_data[staged_span.start : staged_span.properties_end]
        if source_prefix != staged_prefix:
            abort_pending(f"propriedades DAT mudaram em {identity}")
        if source_span.category != "items" or source_span.thing_id not in appearances:
            if source_data[source_span.start : source_span.end] != staged_data[staged_span.start : staged_span.end]:
                abort_pending(f"registro DAT não alvo mudou em {identity}")
    for item in prepared:
        appearance = staged_items[item.client_id].appearances[0]
        if appearance.sprite_ids != item.sprite_ids:
            abort_pending(f"Sprite IDs DAT divergentes no Client ID {item.client_id}")

    written_blocks = read_spr_blocks(targets["spr"], set(expected_tiles), otfi)
    for sprite_id, expected_tile in expected_tiles.items():
        decoded = decode_sprite_rgba(
            written_blocks[sprite_id], transparency=otfi.transparency
        )
        if decoded != expected_tile:
            abort_pending(f"pixels divergentes após reabrir Sprite ID {sprite_id}")
    staged_hashes = _otb_sprite_hashes(targets["otb"])
    for client_id, expected in hashes.items():
        values = staged_hashes.get(client_id, [])
        if not values or any(value != expected for value in values):
            abort_pending(f"SpriteHash divergente no OTB para Client ID {client_id}")

    source_hashes_precommit = {
        name: sha256_file(path) for name, path in protected_sources.items()
    }
    if source_hashes_before != source_hashes_precommit:
        abort_pending("um arquivo de origem mudou durante a importação")

    untouched_before = {
        name: sha256_file(path) for name, path in protected_untouched.items()
    }
    replacements = {
        paths["dat"]: targets["dat"],
        paths["spr"]: targets["spr"],
        paths["otb"]: targets["otb"],
    }
    final_report = _commit_transaction(root, replacements, deep_spr=deep_spr)
    untouched_after = {
        name: sha256_file(path) for name, path in protected_untouched.items()
    }
    if untouched_before != untouched_after:
        raise FormatError(
            "arquivo fora do lote mudou após o commit; restaure pela versão criada"
        )
    output_hashes = {
        name: sha256_file(paths[name]) for name in ("dat", "spr", "otb")
    }

    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "profile": source_report["profile"]["key"],
        "version_backup": backup,
        "sprite_hash_gate": hash_gate,
        "item_count": len(prepared),
        "new_sprite_count": len(blocks),
        "sprite_id_range": [old_sprite_count + 1, expected_sprite_count],
        "items": [asdict(item) for item in prepared],
        "otb_nodes_updated": otb_updates,
        "transaction_committed": True,
        "output_hashes": output_hashes,
        "dat_non_targets_preserved": True,
        "old_sprite_payload_preserved": True,
        "new_sprite_pixels_verified": True,
        "untouched_files_preserved": True,
        "map_byte_equal": untouched_before["otbm"] == untouched_after["otbm"],
        "final_validation_passed": final_report["passed"],
        "warnings": final_report["warnings"],
        "errors": [],
        "passed": True,
    }


def import_items(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    try:
        return _import_items_impl(root, manifest_path, deep_spr=deep_spr)
    except BaseException:
        asset_root = root / "assets"
        if asset_root.is_dir():
            _remove_if_exists(
                [
                    path
                    for path in asset_root.rglob(".*.nwoassets.pending")
                    if path.is_file()
                ]
            )
        raise
