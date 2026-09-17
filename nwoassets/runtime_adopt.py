from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import struct

from . import __version__
from .client import FLAG_NAMES_860, inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import (
    _commit_transaction,
    _otb_sprite_hashes,
    _remove_if_exists,
    _sha256_segment,
    _transaction_path,
    verify_sprite_hash_algorithm,
)
from .otb import OtbNode, inspect_otb, parse_otb_tree
from .otfi import parse_otfi
from .pipeline import inspect_client
from .properties import OTB_FLAG_VALUES, flag_names
from .roundtrip import _dat_property_chunks, scan_dat_record_spans, write_otb_document
from .sprites import RGBA_SIZE, decode_sprite_for_hash, read_spr_blocks, sprite_hash
from .versioning import create_version, require_asset_layout


# Equivalencias diretas entre propriedades booleanas do DAT e flags do OTB.
# A atualizacao e aplicada somente quando a propriedade correspondente mudou no DAT.
_DIRECT_FLAG_RULES = {
    0x0C: ("block_solid", False),
    0x0E: ("block_projectile", False),
    0x0F: ("block_pathfind", False),
    0x19: ("has_height", False),
    0x10: ("pickupable", False),
    0x0D: ("movable", True),
    0x05: ("stackable", False),
    0x14: ("rotatable", False),
    0x11: ("hangable", False),
    0x12: ("vertical", False),
    0x13: ("horizontal", False),
    0x06: ("force_use", False),
}
_STACK_FLAGS = {0x01: 1, 0x02: 2, 0x03: 3}
_MINIMAP_FLAG = 0x1C
_SUPPORTED_PROPERTY_FLAGS = set(_DIRECT_FLAG_RULES) | set(_STACK_FLAGS) | {_MINIMAP_FLAG}


def _property_map(data: bytes, span, source: str) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    for flag, chunk in _dat_property_chunks(data, span, source):
        if flag in result:
            raise FormatError(
                f"{source}: propriedade DAT 0x{flag:02X} duplicada em item {span.thing_id}"
            )
        result[flag] = chunk[1:]
    return result


def _parse_attributes(data: bytes, label: str) -> list[tuple[int, bytes]]:
    if len(data) < 5:
        raise FormatError(f"{label}: no OTB truncado")
    position = 5
    attributes: list[tuple[int, bytes]] = []
    while position < len(data):
        if position + 3 > len(data):
            raise FormatError(f"{label}: atributo OTB truncado")
        attribute = data[position]
        length = struct.unpack_from("<H", data, position + 1)[0]
        position += 3
        if position + length > len(data):
            raise FormatError(f"{label}: payload OTB truncado")
        attributes.append((attribute, data[position : position + length]))
        position += length
    return attributes


def _attribute_u16(attributes: list[tuple[int, bytes]], kind: int) -> int | None:
    values = [payload for attribute, payload in attributes if attribute == kind]
    if not values:
        return None
    if len(values) != 1 or len(values[0]) != 2:
        raise FormatError(f"atributo OTB 0x{kind:02X} invalido ou duplicado")
    return struct.unpack("<H", values[0])[0]


def _replace_attribute(
    attributes: list[tuple[int, bytes]], kind: int, payload: bytes | None
) -> list[tuple[int, bytes]]:
    found = False
    output: list[tuple[int, bytes]] = []
    for attribute, current in attributes:
        if attribute != kind:
            output.append((attribute, current))
            continue
        if found:
            raise FormatError(f"atributo OTB 0x{kind:02X} duplicado")
        found = True
        if payload is not None:
            output.append((kind, payload))
    if not found and payload is not None:
        output.append((kind, payload))
    return output


def _rebuild_node(group: int, flags: int, attributes: list[tuple[int, bytes]]) -> bytes:
    data = bytearray((group,))
    data.extend(struct.pack("<I", flags))
    for attribute, payload in attributes:
        data.append(attribute)
        data.extend(struct.pack("<H", len(payload)))
        data.extend(payload)
    return bytes(data)


def _stack_order(properties: dict[int, bytes]) -> int | None:
    selected = [value for flag, value in _STACK_FLAGS.items() if flag in properties]
    if len(selected) > 1:
        raise FormatError("item DAT possui mais de uma propriedade de stack order")
    return selected[0] if selected else None


def update_otb_from_runtime(
    source: Path,
    destination: Path,
    *,
    sprite_hashes: dict[int, bytes],
    property_changes: dict[int, tuple[dict[int, bytes], dict[int, bytes]]],
    animated: dict[int, bool],
) -> list[dict[str, object]]:
    """Update mapped OTB nodes while preserving all unrelated bytes and payloads."""

    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("destino OTB temporario invalido ou ja existente")
    if any(len(value) != 16 for value in sprite_hashes.values()):
        raise FormatError("todo SpriteHash deve possuir 16 bytes")

    targets = set(sprite_hashes) | set(property_changes) | set(animated)
    file_version, root = parse_otb_tree(source)
    found = {client_id: 0 for client_id in targets}
    changes: list[dict[str, object]] = []
    children: list[OtbNode] = []
    for index, node in enumerate(root.children):
        attributes = _parse_attributes(node.data, f"{source}:item-{index}")
        client_id = _attribute_u16(attributes, 0x11)
        if client_id not in targets:
            children.append(node)
            continue
        server_id = _attribute_u16(attributes, 0x10)
        group = node.data[0]
        before_flags = struct.unpack_from("<I", node.data, 1)[0]
        flags = before_flags
        before_attributes = list(attributes)

        if client_id in property_changes:
            old_properties, new_properties = property_changes[client_id]
            changed_flags = {
                flag
                for flag in set(old_properties) | set(new_properties)
                if old_properties.get(flag) != new_properties.get(flag)
            }
            unsupported = sorted(changed_flags - _SUPPORTED_PROPERTY_FLAGS)
            if unsupported:
                labels = [FLAG_NAMES_860.get(flag, f"0x{flag:02X}") for flag in unsupported]
                raise FormatError(
                    f"Client ID {client_id}: propriedades DAT alteradas sem equivalencia "
                    f"OTB segura: {labels}"
                )
            for dat_flag, (otb_name, inverted) in _DIRECT_FLAG_RULES.items():
                if dat_flag not in changed_flags:
                    continue
                enabled = dat_flag in new_properties
                if inverted:
                    enabled = not enabled
                bit = OTB_FLAG_VALUES[otb_name]
                flags = flags | bit if enabled else flags & ~bit

            if changed_flags & set(_STACK_FLAGS):
                order = _stack_order(new_properties)
                bit = OTB_FLAG_VALUES["always_on_top"]
                flags = flags | bit if order is not None else flags & ~bit
                attributes = _replace_attribute(
                    attributes, 0x2B, None if order is None else bytes((order,))
                )
            if _MINIMAP_FLAG in changed_flags:
                minimap = new_properties.get(_MINIMAP_FLAG)
                if minimap is not None and len(minimap) != 2:
                    raise FormatError(f"Client ID {client_id}: cor de minimapa DAT invalida")
                attributes = _replace_attribute(attributes, 0x21, minimap)

        if client_id in animated:
            bit = OTB_FLAG_VALUES["animation"]
            flags = flags | bit if animated[client_id] else flags & ~bit
        if client_id in sprite_hashes:
            attributes = _replace_attribute(attributes, 0x20, sprite_hashes[client_id])

        rebuilt = _rebuild_node(group, flags, attributes)
        children.append(OtbNode(rebuilt, node.children))
        found[client_id] += 1
        changes.append(
            {
                "server_id": server_id,
                "client_id": client_id,
                "flags_before": f"0x{before_flags:08X}",
                "flags_after": f"0x{flags:08X}",
                "flag_names_before": flag_names(before_flags),
                "flag_names_after": flag_names(flags),
                "attributes_changed": before_attributes != attributes,
            }
        )

    missing = sorted(client_id for client_id, count in found.items() if count == 0)
    if missing:
        raise FormatError(f"Client IDs nao mapeados no OTB: {missing}")
    write_otb_document(file_version, OtbNode(root.data, children), destination)
    return changes


def _copy_verified(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FormatError(f"temporario ja existe: {destination}")
    shutil.copy2(source, destination)
    if sha256_file(source) != sha256_file(destination):
        destination.unlink(missing_ok=True)
        raise FormatError(f"hash da copia diverge: {source}")


def adopt_runtime_assets(
    root: Path,
    *,
    source_dir: Path | None = None,
    deep_spr: bool = False,
) -> dict[str, object]:
    """Adopt an append-only DAT/SPR edit made in the runtime client."""

    root = root.resolve()
    layout = require_asset_layout(root)
    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline canonica reprovou: {baseline['errors']}")
    paths = {name: Path(value) for name, value in baseline["paths"].items()}
    if source_dir is None:
        source_dir = root.parent / "nwo-otclient-mehah-4.0" / "data" / "things" / "860"
    source_dir = source_dir.resolve()
    source_dat = source_dir / paths["dat"].name
    source_spr = source_dir / paths["spr"].name
    if not source_dat.is_file() or not source_spr.is_file():
        raise FormatError(f"DAT/SPR de origem nao encontrados em {source_dir}")
    if source_dat.resolve() == paths["dat"].resolve() or source_spr.resolve() == paths["spr"].resolve():
        raise FormatError("origem runtime deve ser diferente da baseline canonica")

    otfi = parse_otfi(paths["otfi"])
    runtime_spr = inspect_spr(source_spr, otfi, deep=deep_spr)
    runtime_dat = inspect_dat(
        source_dat,
        otfi,
        expected_metadata_reader=int(baseline["profile"]["metadata_reader"]),
        sprite_count=int(runtime_spr["sprite_count"]),
    )
    canonical_count = int(baseline["spr"]["sprite_count"])
    runtime_count = int(runtime_spr["sprite_count"])
    if runtime_count < canonical_count:
        raise FormatError(
            f"SPR runtime remove sprites: {runtime_count} < {canonical_count}"
        )
    old_body_size = paths["spr"].stat().st_size - int(baseline["spr"]["table_end"])
    old_body_hash = _sha256_segment(paths["spr"], int(baseline["spr"]["table_end"]))
    runtime_old_body_hash = _sha256_segment(
        source_spr, int(runtime_spr["table_end"]), old_body_size
    )
    if old_body_hash != runtime_old_body_hash:
        raise FormatError("SPR runtime alterou payload de Sprite IDs existentes; lote bloqueado")

    canonical_data = paths["dat"].read_bytes()
    runtime_data = source_dat.read_bytes()
    if canonical_data[:12] != runtime_data[:12]:
        raise FormatError("header/maximos DAT runtime divergem da baseline")
    old_spans = scan_dat_record_spans(canonical_data, otfi, str(paths["dat"]))
    new_spans = scan_dat_record_spans(runtime_data, otfi, str(source_dat))
    if len(old_spans) != len(new_spans):
        raise FormatError("quantidade de registros DAT runtime diverge da baseline")

    changed_records: list[dict[str, object]] = []
    appearance_changes: set[int] = set()
    property_changes: dict[int, tuple[dict[int, bytes], dict[int, bytes]]] = {}
    animated: dict[int, bool] = {}
    new_items = {}
    for old, new in zip(old_spans, new_spans):
        identity = (old.category, old.thing_id)
        if identity != (new.category, new.thing_id):
            raise FormatError("ordem/identidade dos registros DAT runtime diverge")
        old_record = canonical_data[old.start : old.end]
        new_record = runtime_data[new.start : new.end]
        if old_record == new_record:
            continue
        if old.category != "items":
            raise FormatError(f"alteracao DAT fora de items bloqueada: {identity}")
        old_properties = _property_map(canonical_data, old, str(paths["dat"]))
        new_properties = _property_map(runtime_data, new, str(source_dat))
        properties_semantic = old_properties != new_properties
        appearance_changed = canonical_data[old.properties_end : old.end] != runtime_data[new.properties_end : new.end]
        if properties_semantic:
            property_changes[old.thing_id] = (old_properties, new_properties)
        if appearance_changed:
            appearance_changes.add(old.thing_id)
            animated[old.thing_id] = any(view.frames > 1 for view in new.appearances)
        new_items[old.thing_id] = new
        changed_records.append(
            {
                "category": old.category,
                "client_id": old.thing_id,
                "property_bytes_changed": canonical_data[old.start : old.properties_end]
                != runtime_data[new.start : new.properties_end],
                "properties_semantic_changed": properties_semantic,
                "appearance_changed": appearance_changed,
                "old_size": len(old_record),
                "new_size": len(new_record),
            }
        )
    if not changed_records and runtime_count == canonical_count:
        raise FormatError("DAT/SPR runtime nao contem alteracoes para adotar")

    sprite_ids: set[int] = set()
    selected: dict[int, tuple[int, ...]] = {}
    for client_id in sorted(appearance_changes):
        appearance = new_items[client_id].appearances[0]
        first_view_count = appearance.width * appearance.height * appearance.layers
        selected[client_id] = appearance.sprite_ids[:first_view_count]
        sprite_ids.update(sprite_id for sprite_id in selected[client_id] if sprite_id)
    blocks = read_spr_blocks(source_spr, sprite_ids, otfi)
    blank = bytes(RGBA_SIZE)
    sprite_hashes: dict[int, bytes] = {}
    for client_id, ids in selected.items():
        tiles = [
            blank
            if sprite_id == 0
            else decode_sprite_for_hash(blocks[sprite_id], transparency=otfi.transparency)
            for sprite_id in ids
        ]
        sprite_hashes[client_id] = sprite_hash(tiles)

    source_hashes = {"dat": sha256_file(source_dat), "spr": sha256_file(source_spr)}
    canonical_before = {
        path: sha256_file(path)
        for path in (layout["root"]).rglob("*")
        if path.is_file()
    }
    hash_gate = verify_sprite_hash_algorithm(paths["dat"], paths["spr"], paths["otb"], otfi)
    if not hash_gate["passed"]:
        raise FormatError(f"algoritmo SpriteHash reprovou na baseline: {hash_gate['mismatches'][:3]}")
    backup = create_version(root)
    pending_dat = _transaction_path(paths["dat"], "pending")
    pending_spr = _transaction_path(paths["spr"], "pending")
    pending_otb = _transaction_path(paths["otb"], "pending")
    pending = [pending_dat, pending_spr, pending_otb]
    stale = [str(path) for path in pending if path.exists()]
    if stale:
        raise FormatError(f"temporarios pendentes impedem a adocao: {stale}")
    try:
        _copy_verified(source_dat, pending_dat)
        _copy_verified(source_spr, pending_spr)
        otb_changes = update_otb_from_runtime(
            paths["otb"],
            pending_otb,
            sprite_hashes=sprite_hashes,
            property_changes=property_changes,
            animated=animated,
        )
        pending_otb_report = inspect_otb(pending_otb)
        if pending_otb_report["malformed_attributes"]:
            raise FormatError("OTB preparado possui atributos malformados")
        written_hashes = _otb_sprite_hashes(pending_otb)
        for client_id, expected in sprite_hashes.items():
            values = written_hashes.get(client_id, [])
            if not values or any(value != expected for value in values):
                raise FormatError(f"SpriteHash nao persistiu para Client ID {client_id}")
        if source_hashes != {"dat": sha256_file(source_dat), "spr": sha256_file(source_spr)}:
            raise FormatError("arquivos runtime mudaram durante a preparacao")
        if canonical_before != {
            path: sha256_file(path)
            for path in canonical_before
        }:
            raise FormatError("asset canonico mudou durante a preparacao")
        final = _commit_transaction(
            root,
            {paths["dat"]: pending_dat, paths["spr"]: pending_spr, paths["otb"]: pending_otb},
            deep_spr=deep_spr,
        )
    except BaseException:
        _remove_if_exists(pending)
        raise

    for path, digest in canonical_before.items():
        if path not in {paths["dat"], paths["spr"], paths["otb"]} and sha256_file(path) != digest:
            raise FormatError(f"asset fora do lote foi alterado: {path}")
    return {
        "tool_version": __version__,
        "generated_at": datetime.now().astimezone().isoformat(),
        "root": str(root),
        "source_dir": str(source_dir),
        "version_backup": backup,
        "source_hashes": source_hashes,
        "sprite_hash_gate": hash_gate,
        "canonical_sprite_count_before": canonical_count,
        "canonical_sprite_count_after": runtime_count,
        "new_sprite_ids": [canonical_count + 1, runtime_count] if runtime_count > canonical_count else None,
        "changed_records": changed_records,
        "appearance_client_ids": sorted(appearance_changes),
        "property_client_ids": sorted(property_changes),
        "otb_changes": otb_changes,
        "output_hashes": {
            "dat": sha256_file(paths["dat"]),
            "spr": sha256_file(paths["spr"]),
            "otb": sha256_file(paths["otb"]),
        },
        "transaction_committed": True,
        "old_sprite_payload_preserved": True,
        "untouched_assets_preserved": True,
        "final_validation_passed": final["passed"],
        "warnings": final["warnings"],
        "errors": [],
        "passed": True,
    }
