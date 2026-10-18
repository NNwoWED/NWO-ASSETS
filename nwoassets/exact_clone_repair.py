from __future__ import annotations

from collections import defaultdict, deque
from collections import Counter
import csv
from dataclasses import dataclass
from pathlib import Path
import struct

from .appearance_sheet import split_flattened_z_sheet
from .atomic import atomic_binary_output
from .client import inspect_dat
from .clone_item_importer import _otb_node_ids, clone_otb_node
from .content import sha256_file
from .errors import FormatError
from .importer import (
    _commit_transaction,
    _remove_if_exists,
    _transaction_path,
    verify_sprite_hash_algorithm,
)
from .item_xml_clone import clone_xml_definitions
from .otb import OtbNode, inspect_otb, parse_otb_tree
from .otfi import parse_otfi
from .pipeline import inspect_client
from .png import normalize_rgba, read_png_rgba
from .remake_importer import _assert_map_targets_absent, _write_dat_remake_records
from .roundtrip import scan_dat_record_spans, write_otb_document
from .sprites import RGBA_SIZE, decode_sprite_rgba, read_spr_blocks, sprite_hash
from .versioning import create_version, require_asset_layout


@dataclass(frozen=True)
class ExactCloneEntry:
    sequence: int
    source_client_id: int
    target_server_id: int
    target_client_id: int
    source_path: Path
    sprite_id_start: int
    sprite_id_end: int


FIELDS = (
    "sequence", "source_client_id", "target_server_id", "target_client_id",
    "source_path", "sprite_id_start", "sprite_id_end",
)


def read_exact_clone_manifest(path: Path) -> list[ExactCloneEntry]:
    path = path.resolve()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise FormatError(f"{path}: cabecalho esperado: {','.join(FIELDS)}")
        entries: list[ExactCloneEntry] = []
        for row_number, row in enumerate(reader, 2):
            try:
                sequence = int(row["sequence"])
                source_client_id = int(row["source_client_id"])
                target_server_id = int(row["target_server_id"])
                target_client_id = int(row["target_client_id"])
                sprite_id_start = int(row["sprite_id_start"])
                sprite_id_end = int(row["sprite_id_end"])
            except (TypeError, ValueError) as exc:
                raise FormatError(f"{path}:{row_number}: valor numerico invalido") from exc
            if min(
                source_client_id, target_server_id, target_client_id,
                sprite_id_start, sprite_id_end,
            ) < 1 or sprite_id_end < sprite_id_start:
                raise FormatError(f"{path}:{row_number}: IDs/range invalidos")
            source = Path(row["source_path"])
            if not source.is_absolute():
                source = path.parent / source
            source = source.resolve()
            if source.suffix.casefold() != ".png" or not source.is_file():
                raise FormatError(f"{path}:{row_number}: PNG ausente: {source}")
            entries.append(ExactCloneEntry(
                sequence, source_client_id, target_server_id, target_client_id,
                source, sprite_id_start, sprite_id_end,
            ))
    if not entries or [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError(f"{path}: sequence deve ser continua a partir de 1")
    for field in ("source_client_id", "target_server_id", "target_client_id", "source_path"):
        values = [getattr(entry, field) for entry in entries]
        if len(values) != len(set(values)):
            raise FormatError(f"{path}: {field} duplicado")
    ranges = [
        sprite_id
        for entry in entries
        for sprite_id in range(entry.sprite_id_start, entry.sprite_id_end + 1)
    ]
    if len(ranges) != len(set(ranges)):
        raise FormatError(f"{path}: ranges de Sprite IDs se sobrepoem")
    return entries


def write_otb_exact_clones(
    source: Path,
    destination: Path,
    replacements: dict[int, OtbNode],
) -> None:
    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("destino OTB temporario invalido")
    version, root = parse_otb_tree(source)
    children: list[OtbNode] = []
    found: set[int] = set()
    for index, node in enumerate(root.children):
        server_id, _ = _otb_node_ids(node, f"{source}:item-{index}")
        if server_id in replacements:
            children.append(replacements[server_id])
            found.add(server_id)
        else:
            children.append(node)
    missing = sorted(set(replacements) - found)
    if missing:
        raise FormatError(f"Server IDs OTB alvo ausentes: {missing}")
    write_otb_document(version, OtbNode(root.data, children), destination)


def repair_exact_item_clones(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = True,
    dry_run: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    layout = require_asset_layout(root)
    entries = read_exact_clone_manifest(manifest_path)
    sprites_root = (root / "sprites").resolve()
    if not all(entry.source_path.is_relative_to(sprites_root) for entry in entries):
        raise FormatError("PNGs devem estar em NWO-ASSETS/sprites")

    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline reprovada: {baseline['errors']}")
    paths = {name: Path(value) for name, value in baseline["paths"].items()}
    paths["xml"] = layout["items"] / "items.xml"
    otfi = parse_otfi(paths["otfi"])
    if not (otfi.extended and otfi.transparency):
        raise FormatError("perfil OTFI incompativel com reparo exato")
    hash_gate = verify_sprite_hash_algorithm(paths["dat"], paths["spr"], paths["otb"], otfi)
    if not hash_gate["passed"]:
        raise FormatError("SpriteHash da baseline diverge")

    data = paths["dat"].read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(paths["dat"]))
    items = {span.thing_id: span for span in spans if span.category == "items"}
    _, otb_root = parse_otb_tree(paths["otb"])
    by_server: dict[int, tuple[int, OtbNode]] = {}
    by_client: dict[int, list[tuple[int, OtbNode]]] = defaultdict(list)
    for index, node in enumerate(otb_root.children):
        server_id, client_id = _otb_node_ids(node, f"{paths['otb']}:item-{index}")
        if server_id is not None and client_id is not None:
            by_server[server_id] = (client_id, node)
            by_client[client_id].append((server_id, node))
    for entry in entries:
        if entry.source_client_id not in items or entry.target_client_id not in items:
            raise FormatError(f"Client ID DAT ausente na linha {entry.sequence}")
        if len(by_client.get(entry.source_client_id, [])) != 1:
            raise FormatError(f"Client ID origem ambiguo no OTB: {entry.source_client_id}")
        if by_server.get(entry.target_server_id, (None,))[0] != entry.target_client_id:
            raise FormatError(
                f"SID {entry.target_server_id} nao aponta para CID {entry.target_client_id}"
            )

    sprite_ids_to_read = {
        sprite_id
        for entry in entries
        for sprite_id in range(entry.sprite_id_start, entry.sprite_id_end + 1)
    }
    sprite_ids_to_read.update(
        sprite_id
        for entry in entries
        for sprite_id in items[entry.source_client_id].appearances[0].sprite_ids
        if sprite_id
    )
    blocks = read_spr_blocks(paths["spr"], sprite_ids_to_read, otfi)
    blank = bytes(RGBA_SIZE)
    dat_replacements: dict[int, tuple[bytes, bytes]] = {}
    otb_replacements: dict[int, OtbNode] = {}
    target_to_source_sid: dict[int, int] = {}
    reports: list[dict[str, object]] = []
    source_png_hashes = {str(entry.source_path): sha256_file(entry.source_path) for entry in entries}
    properties_equal_before = 0
    layout_equal_before = 0
    otb_equal_before = 0
    alpha_group_sets_exact = 0
    reordered_item_count = 0
    for entry in entries:
        source_span = items[entry.source_client_id]
        target_span = items[entry.target_client_id]
        source_appearance = source_span.appearances[0]
        target_appearance = target_span.appearances[0]
        if len(source_span.appearances) != 1 or source_appearance.frames != 1:
            raise FormatError(
                f"CID origem {entry.source_client_id}: somente item estatico de um grupo e suportado"
            )
        source_layout = (
            source_appearance.width, source_appearance.height, source_appearance.layers,
            source_appearance.pattern_x, source_appearance.pattern_y,
            source_appearance.pattern_z, source_appearance.frames,
        )
        target_layout = (
            target_appearance.width, target_appearance.height, target_appearance.layers,
            target_appearance.pattern_x, target_appearance.pattern_y,
            target_appearance.pattern_z, target_appearance.frames,
        )
        source_properties = data[source_span.start:source_span.properties_end]
        target_properties = data[target_span.start:target_span.properties_end]
        properties_equal_before += source_properties == target_properties
        layout_equal_before += source_layout == target_layout

        image = normalize_rgba(read_png_rgba(
            entry.source_path,
            max_width=(
                otfi.sprite_size * source_appearance.width * source_appearance.layers
                * source_appearance.pattern_x * source_appearance.pattern_z
            ),
            max_height=(
                otfi.sprite_size * source_appearance.height * source_appearance.pattern_y
            ),
        ))
        groups = split_flattened_z_sheet(
            image,
            sprite_size=otfi.sprite_size,
            width=source_appearance.width,
            height=source_appearance.height,
            layers=source_appearance.layers,
            pattern_x=source_appearance.pattern_x,
            pattern_y=source_appearance.pattern_y,
            pattern_z=source_appearance.pattern_z,
            frames=source_appearance.frames,
        )
        group_size = (
            source_appearance.width * source_appearance.height * source_appearance.layers
        )
        reference_tiles = tuple(
            blank
            if sprite_id == 0
            else decode_sprite_rgba(blocks[sprite_id], transparency=otfi.transparency)
            for sprite_id in source_appearance.sprite_ids
        )
        reference_groups = tuple(
            reference_tiles[index:index + group_size]
            for index in range(0, len(reference_tiles), group_size)
        )

        def alpha_key(group: tuple[bytes, ...]) -> tuple[bytes, ...]:
            return tuple(tile[3::4] for tile in group)

        reference_keys = tuple(alpha_key(group) for group in reference_groups)
        new_keys = tuple(alpha_key(group) for group in groups)
        alpha_multiset_exact = Counter(reference_keys) == Counter(new_keys)
        if alpha_multiset_exact:
            alpha_group_sets_exact += 1
            by_key: dict[tuple[bytes, ...], deque[tuple[bytes, ...]]] = defaultdict(deque)
            for key, group in zip(new_keys, groups):
                by_key[key].append(group)
            ordered_groups = tuple(by_key[key].popleft() for key in reference_keys)
        elif len(groups) == 1:
            ordered_groups = groups
        else:
            raise FormatError(
                f"CID origem {entry.source_client_id}: sprites recoloridos nao preservam "
                "o conjunto de mascaras alfa da referencia; ordem exata ambigua"
            )
        groups_reordered = ordered_groups != groups
        reordered_item_count += groups_reordered
        ordered_tiles = tuple(tile for group in ordered_groups for tile in group)
        if len(ordered_tiles) != len(source_appearance.sprite_ids):
            raise FormatError(f"CID origem {entry.source_client_id}: quantidade visual diverge")

        available: dict[bytes, deque[int]] = defaultdict(deque)
        for sprite_id in range(entry.sprite_id_start, entry.sprite_id_end + 1):
            available[decode_sprite_rgba(
                blocks[sprite_id], transparency=otfi.transparency
            )].append(sprite_id)
        new_sprite_ids: list[int] = []
        for tile in ordered_tiles:
            if tile == blank:
                new_sprite_ids.append(0)
                continue
            candidates = available.get(tile)
            if not candidates:
                raise FormatError(
                    f"CID alvo {entry.target_client_id}: pixels do PNG nao encontrados "
                    f"no range {entry.sprite_id_start}-{entry.sprite_id_end}"
                )
            new_sprite_ids.append(candidates.popleft())
        leftovers = sum(len(values) for values in available.values())
        if leftovers:
            raise FormatError(
                f"CID alvo {entry.target_client_id}: {leftovers} sprites do range nao consumidos"
            )

        sprite_bytes = len(source_appearance.sprite_ids) * 4
        source_visual = data[source_span.properties_end:source_span.end]
        appearance_prefix = source_visual[:-sprite_bytes]
        appearance = appearance_prefix + b"".join(
            struct.pack("<I", sprite_id) for sprite_id in new_sprite_ids
        )
        dat_replacements[entry.target_client_id] = (source_properties, appearance)

        digest = sprite_hash(list(ordered_tiles[:group_size]))
        source_sid, source_node = by_client[entry.source_client_id][0]
        source_flags = struct.unpack_from("<I", source_node.data, 1)[0]
        cloned_node = clone_otb_node(
            source_node,
            server_id=entry.target_server_id,
            client_id=entry.target_client_id,
            digest=digest,
            animated=bool(source_flags & (1 << 24)),
        )
        otb_replacements[entry.target_server_id] = cloned_node
        target_to_source_sid[entry.target_server_id] = source_sid
        otb_equal_before += by_server[entry.target_server_id][1].data == cloned_node.data
        reports.append({
            "sequence": entry.sequence,
            "source_server_id": source_sid,
            "source_client_id": entry.source_client_id,
            "target_server_id": entry.target_server_id,
            "target_client_id": entry.target_client_id,
            "source_path": str(entry.source_path),
            "source_sha256": source_png_hashes[str(entry.source_path)],
            "layout": {
                "width": source_appearance.width,
                "height": source_appearance.height,
                "layers": source_appearance.layers,
                "pattern_x": source_appearance.pattern_x,
                "pattern_y": source_appearance.pattern_y,
                "pattern_z": source_appearance.pattern_z,
                "frames": source_appearance.frames,
            },
            "sprite_id_range_reused": [entry.sprite_id_start, entry.sprite_id_end],
            "alpha_group_set_exact": alpha_multiset_exact,
            "groups_reordered_to_reference": groups_reordered,
            "sprite_hash": digest.hex().upper(),
        })

    original_xml = paths["xml"].read_bytes()
    prepared_xml, xml_report = clone_xml_definitions(original_xml, target_to_source_sid)
    maps = sorted(layout["world"].glob("*.otbm"))
    if len(maps) != 1:
        raise FormatError("esperado exatamente um mapa canonico")
    map_scan = _assert_map_targets_absent(maps[0], set(otb_replacements))
    common: dict[str, object] = {
        "root": str(root),
        "manifest": str(manifest_path),
        "item_count": len(entries),
        "reference_kind": "client_id_from_png_filename",
        "before": {
            "dat_properties_exact": properties_equal_before,
            "dat_layout_exact": layout_equal_before,
            "otb_nodes_exact": otb_equal_before,
        },
        "visual_order": {
            "alpha_group_sets_exact": alpha_group_sets_exact,
            "single_group_art_variants": len(entries) - alpha_group_sets_exact,
            "items_reordered_to_reference": reordered_item_count,
        },
        "xml": xml_report,
        "map_scan": map_scan,
        "spr_unchanged": True,
        "items": reports,
    }
    if dry_run:
        return {**common, "dry_run": True, "passed": True}

    pending = {
        name: _transaction_path(paths[name], "pending")
        for name in ("dat", "otb", "xml")
    }
    if any(path.exists() for path in pending.values()):
        raise FormatError("arquivos temporarios de reparo exato ja existem")
    protected = {
        path: sha256_file(path)
        for path in (root / "assets").rglob("*")
        if path.is_file()
    }
    backup = create_version(root)
    try:
        _write_dat_remake_records(paths["dat"], pending["dat"], otfi, dat_replacements)
        write_otb_exact_clones(paths["otb"], pending["otb"], otb_replacements)
        with atomic_binary_output(pending["xml"]) as stream:
            stream.write(prepared_xml)
        inspect_dat(
            pending["dat"], otfi,
            expected_metadata_reader=int(baseline["profile"]["metadata_reader"]),
            sprite_count=int(baseline["spr"]["sprite_count"]),
        )
        pending_otb = inspect_otb(pending["otb"])
        if pending_otb["malformed_attributes"]:
            raise FormatError("OTB preparado possui atributos malformados")
        staged_data = pending["dat"].read_bytes()
        staged_spans = scan_dat_record_spans(staged_data, otfi, str(pending["dat"]))
        staged_by_key = {(span.category, span.thing_id): span for span in staged_spans}
        for span in spans:
            staged = staged_by_key[(span.category, span.thing_id)]
            if span.category == "items" and span.thing_id in dat_replacements:
                expected = b"".join(dat_replacements[span.thing_id])
                if staged_data[staged.start:staged.end] != expected:
                    raise FormatError(f"CID alvo {span.thing_id}: DAT nao persistiu")
            elif data[span.start:span.end] != staged_data[staged.start:staged.end]:
                raise FormatError(f"registro DAT fora do alvo mudou: {span.category} {span.thing_id}")
        _, staged_otb = parse_otb_tree(pending["otb"])
        for index, (before, after) in enumerate(zip(otb_root.children, staged_otb.children)):
            server_id, _ = _otb_node_ids(before, f"OTB:{index}")
            expected = otb_replacements.get(server_id, before)
            if after.data != expected.data or after.children != expected.children:
                raise FormatError(f"SID {server_id}: OTB preparado diverge")
        if pending["xml"].read_bytes() != prepared_xml:
            raise FormatError("items.xml preparado nao persistiu")
        if protected != {path: sha256_file(path) for path in protected}:
            raise FormatError("baseline mudou durante a preparacao")
        if source_png_hashes != {
            str(entry.source_path): sha256_file(entry.source_path) for entry in entries
        }:
            raise FormatError("PNG de origem mudou durante a preparacao")
        final = _commit_transaction(
            root,
            {
                paths["dat"]: pending["dat"],
                paths["otb"]: pending["otb"],
                paths["xml"]: pending["xml"],
            },
            deep_spr=deep_spr,
        )
    except BaseException:
        _remove_if_exists(list(pending.values()))
        raise
    if not final["passed"]:
        raise FormatError("validacao final falhou")
    for path, digest in protected.items():
        if path not in {paths["dat"], paths["otb"], paths["xml"]} and sha256_file(path) != digest:
            raise FormatError(f"asset fora do reparo mudou: {path}")
    return {
        **common,
        "version_backup": backup,
        "transaction_committed": True,
        "final_validation_passed": True,
        "warnings": final["warnings"],
        "errors": [],
        "passed": True,
    }
