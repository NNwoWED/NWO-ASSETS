from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import csv
from pathlib import Path
import struct

from .atomic import atomic_binary_output
from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import _commit_transaction, _remove_if_exists, _transaction_path
from .otb import OtbNode, inspect_otb, parse_otb_tree
from .otfi import parse_otfi
from .pipeline import inspect_client
from .roundtrip import (
    _dat_property_chunks,
    scan_dat_record_spans,
    write_otb_document,
)
from .versioning import create_version, require_asset_layout


DAT_GROUND_FLAG = 0x00
OTB_GROUND_ATTRIBUTE = 0x14
OTB_GROUND_GROUP = 1


@dataclass(frozen=True)
class GroundSpeedEdit:
    sequence: int
    server_id: int
    client_id: int
    ground_speed: int


def read_ground_speed_manifest(path: Path) -> list[GroundSpeedEdit]:
    if not path.is_file():
        raise FormatError(f"manifesto de ground speed nao encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"sequence", "server_id", "client_id", "ground_speed"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise FormatError(
                "manifesto exige sequence, server_id, client_id e ground_speed"
            )
        entries: list[GroundSpeedEdit] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                entry = GroundSpeedEdit(
                    sequence=int(row["sequence"]),
                    server_id=int(row["server_id"]),
                    client_id=int(row["client_id"]),
                    ground_speed=int(row["ground_speed"]),
                )
            except (TypeError, ValueError) as exc:
                raise FormatError(f"linha {row_number}: valor numerico invalido") from exc
            if not 0 <= entry.ground_speed <= 0xFFFF:
                raise FormatError(
                    f"linha {row_number}: ground_speed fora de 0..65535"
                )
            entries.append(entry)
    if not entries:
        raise FormatError("manifesto de ground speed esta vazio")
    if [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError("sequence deve iniciar em 1 e ser continua")
    server_ids = [entry.server_id for entry in entries]
    if len(server_ids) != len(set(server_ids)):
        raise FormatError("manifesto contem Server IDs duplicados")
    client_targets: dict[int, int] = {}
    for entry in entries:
        previous = client_targets.setdefault(entry.client_id, entry.ground_speed)
        if previous != entry.ground_speed:
            raise FormatError(
                f"Client ID {entry.client_id} recebeu ground speeds conflitantes"
            )
    return entries


def _otb_attributes(node: OtbNode, source: str) -> tuple[int, int, dict[int, bytes]]:
    if len(node.data) < 5:
        raise FormatError(f"{source}: no OTB truncado")
    group = node.data[0]
    flags = struct.unpack_from("<I", node.data, 1)[0]
    position = 5
    attributes: dict[int, bytes] = {}
    while position < len(node.data):
        if position + 3 > len(node.data):
            raise FormatError(f"{source}: atributo OTB truncado")
        attribute = node.data[position]
        length = struct.unpack_from("<H", node.data, position + 1)[0]
        position += 3
        if position + length > len(node.data):
            raise FormatError(f"{source}: payload OTB truncado")
        if attribute in attributes:
            raise FormatError(f"{source}: atributo OTB 0x{attribute:02X} duplicado")
        attributes[attribute] = node.data[position : position + length]
        position += length
    return group, flags, attributes


def read_otb_ground_speeds(path: Path) -> dict[int, dict[str, int]]:
    _, root = parse_otb_tree(path)
    result: dict[int, dict[str, int]] = {}
    for index, node in enumerate(root.children):
        group, flags, attributes = _otb_attributes(node, f"{path}:item-{index}")
        server_raw = attributes.get(0x10)
        client_raw = attributes.get(0x11)
        speed_raw = attributes.get(OTB_GROUND_ATTRIBUTE)
        if group != OTB_GROUND_GROUP:
            continue
        if server_raw is None or len(server_raw) != 2:
            raise FormatError(f"{path}: piso OTB {index} sem Server ID valido")
        if client_raw is None or len(client_raw) != 2:
            raise FormatError(f"{path}: piso OTB {index} sem Client ID valido")
        if speed_raw is None or len(speed_raw) != 2:
            raise FormatError(f"{path}: piso OTB {index} sem ground speed valido")
        server_id = struct.unpack("<H", server_raw)[0]
        if server_id in result:
            raise FormatError(f"{path}: Server ID OTB duplicado: {server_id}")
        result[server_id] = {
            "client_id": struct.unpack("<H", client_raw)[0],
            "ground_speed": struct.unpack("<H", speed_raw)[0],
            "flags": flags,
        }
    return result


def read_dat_ground_speeds(
    data: bytes, otfi, source: str
) -> dict[int, int]:
    result: dict[int, int] = {}
    for span in scan_dat_record_spans(data, otfi, source):
        if span.category != "items":
            continue
        ground_chunks = [
            chunk
            for flag, chunk in _dat_property_chunks(data, span, source)
            if flag == DAT_GROUND_FLAG
        ]
        if not ground_chunks:
            continue
        if len(ground_chunks) != 1 or len(ground_chunks[0]) != 3:
            raise FormatError(f"{source}: ground speed DAT invalido no item {span.thing_id}")
        result[span.thing_id] = struct.unpack("<H", ground_chunks[0][1:])[0]
    return result


def write_dat_ground_speeds(
    source: Path,
    destination: Path,
    otfi,
    edits: dict[int, int],
) -> dict[int, dict[str, int]]:
    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("destino DAT temporario invalido ou ja existente")
    data = source.read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(source))
    items = {span.thing_id: span for span in spans if span.category == "items"}
    missing = sorted(set(edits) - set(items))
    if missing:
        raise FormatError(f"Client IDs DAT inexistentes: {missing}")

    replacements: dict[int, bytes] = {}
    changes: dict[int, dict[str, int]] = {}
    for client_id, ground_speed in edits.items():
        chunks = _dat_property_chunks(data, items[client_id], str(source))
        found = [chunk for flag, chunk in chunks if flag == DAT_GROUND_FLAG]
        if len(found) != 1 or len(found[0]) != 3:
            raise FormatError(f"Client ID {client_id} nao possui ground speed DAT unico")
        before = struct.unpack("<H", found[0][1:])[0]
        encoded = b"".join(
            bytes([flag]) + struct.pack("<H", ground_speed)
            if flag == DAT_GROUND_FLAG
            else chunk
            for flag, chunk in chunks
        ) + b"\xFF"
        replacements[client_id] = encoded
        changes[client_id] = {"before": before, "after": ground_speed}

    with atomic_binary_output(destination) as output:
        output.write(data[:12])
        for span in spans:
            if span.category == "items" and span.thing_id in replacements:
                output.write(replacements[span.thing_id])
                output.write(data[span.properties_end : span.end])
            else:
                output.write(data[span.start : span.end])
    return changes


def write_otb_ground_speeds(
    source: Path,
    destination: Path,
    edits: dict[int, int],
) -> dict[int, dict[str, int]]:
    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("destino OTB temporario invalido ou ja existente")
    file_version, root = parse_otb_tree(source)
    changes: dict[int, dict[str, int]] = {}
    new_children: list[OtbNode] = []
    found: set[int] = set()
    for index, node in enumerate(root.children):
        group, _, attributes = _otb_attributes(node, f"{source}:item-{index}")
        server_raw = attributes.get(0x10)
        server_id = struct.unpack("<H", server_raw)[0] if server_raw and len(server_raw) == 2 else None
        if server_id is None or server_id not in edits:
            new_children.append(node)
            continue
        if group != OTB_GROUND_GROUP:
            raise FormatError(f"Server ID {server_id} nao pertence ao grupo ground")
        speed_raw = attributes.get(OTB_GROUND_ATTRIBUTE)
        if speed_raw is None or len(speed_raw) != 2:
            raise FormatError(f"Server ID {server_id} nao possui ground speed OTB valido")
        before = struct.unpack("<H", speed_raw)[0]
        target = edits[server_id]
        position = 5
        new_data = bytearray(node.data)
        while position < len(node.data):
            attribute = node.data[position]
            length = struct.unpack_from("<H", node.data, position + 1)[0]
            payload_position = position + 3
            if attribute == OTB_GROUND_ATTRIBUTE:
                struct.pack_into("<H", new_data, payload_position, target)
                break
            position = payload_position + length
        new_children.append(OtbNode(bytes(new_data), node.children))
        changes[server_id] = {"before": before, "after": target}
        found.add(server_id)
    missing = sorted(set(edits) - found)
    if missing:
        raise FormatError(f"Server IDs de piso inexistentes no OTB: {missing}")
    write_otb_document(file_version, OtbNode(root.data, new_children), destination)
    return changes


def edit_ground_speeds(
    root: Path, manifest_path: Path, *, deep_spr: bool = False
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    require_asset_layout(root)
    entries = read_ground_speed_manifest(manifest_path)
    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline de origem reprovou: {baseline['errors']}")
    paths = {name: Path(value) for name, value in baseline["paths"].items()}
    otfi = parse_otfi(paths["otfi"])
    source_dat = paths["dat"].read_bytes()
    dat_items = read_dat_ground_speeds(source_dat, otfi, str(paths["dat"]))
    otb_items = read_otb_ground_speeds(paths["otb"])

    dat_targets: dict[int, int] = {}
    otb_targets: dict[int, int] = {}
    resolved: list[dict[str, int]] = []
    for entry in entries:
        item = otb_items.get(entry.server_id)
        if item is None:
            raise FormatError(f"Server ID {entry.server_id} nao e um piso OTB")
        if item["client_id"] != entry.client_id:
            raise FormatError(
                f"Server ID {entry.server_id}: manifesto informa Client ID "
                f"{entry.client_id}, mas o OTB mapeia {item['client_id']}"
            )
        if entry.client_id not in dat_items:
            raise FormatError(f"Client ID {entry.client_id} nao e um piso DAT")
        if dat_items[entry.client_id] != item["ground_speed"]:
            raise FormatError(
                f"Server ID {entry.server_id}/Client ID {entry.client_id}: "
                f"DAT={dat_items[entry.client_id]} e OTB={item['ground_speed']} divergem"
            )
        previous = dat_targets.setdefault(entry.client_id, entry.ground_speed)
        if previous != entry.ground_speed:
            raise FormatError(f"Client ID {entry.client_id} recebeu alvos conflitantes")
        otb_targets[entry.server_id] = entry.ground_speed
        resolved.append({
            "sequence": entry.sequence,
            "server_id": entry.server_id,
            "client_id": entry.client_id,
            "before": item["ground_speed"],
            "after": entry.ground_speed,
        })

    changed_dat = {
        client_id: speed
        for client_id, speed in dat_targets.items()
        if dat_items[client_id] != speed
    }
    changed_otb = {
        server_id: speed
        for server_id, speed in otb_targets.items()
        if otb_items[server_id]["ground_speed"] != speed
    }
    if not changed_dat and not changed_otb:
        raise FormatError("o manifesto nao produz nenhuma alteracao na baseline atual")

    target_dat = _transaction_path(paths["dat"], "pending")
    target_otb = _transaction_path(paths["otb"], "pending")
    targets = {paths["dat"]: target_dat, paths["otb"]: target_otb}
    stale = [str(path) for path in targets.values() if path.exists()]
    if stale:
        raise FormatError(f"arquivos temporarios ja existem: {stale}")
    protected = {
        path: sha256_file(path)
        for path in (root / "assets").rglob("*")
        if path.is_file()
    }
    backup = create_version(root)
    try:
        dat_changes = write_dat_ground_speeds(
            paths["dat"], target_dat, otfi, changed_dat
        )
        otb_changes = write_otb_ground_speeds(
            paths["otb"], target_otb, changed_otb
        )
        pending_spr = inspect_spr(paths["spr"], otfi, deep=deep_spr)
        inspect_dat(
            target_dat,
            otfi,
            expected_metadata_reader=int(baseline["profile"]["metadata_reader"]),
            sprite_count=int(pending_spr["sprite_count"]),
        )
        pending_otb = inspect_otb(target_otb)
        if pending_otb["malformed_attributes"]:
            raise FormatError("OTB preparado possui atributos malformados")
        after_dat = read_dat_ground_speeds(
            target_dat.read_bytes(), otfi, str(target_dat)
        )
        after_otb = read_otb_ground_speeds(target_otb)
        for client_id, speed in changed_dat.items():
            if after_dat.get(client_id) != speed:
                raise FormatError(f"validacao DAT divergiu no Client ID {client_id}")
        for server_id, speed in changed_otb.items():
            if after_otb.get(server_id, {}).get("ground_speed") != speed:
                raise FormatError(f"validacao OTB divergiu no Server ID {server_id}")
    except BaseException:
        _remove_if_exists(list(targets.values()))
        raise

    if {path: sha256_file(path) for path in protected} != protected:
        _remove_if_exists(list(targets.values()))
        raise FormatError("um asset oficial mudou durante a preparacao")
    final = _commit_transaction(root, targets, deep_spr=deep_spr)
    for path, digest in protected.items():
        if path not in targets and sha256_file(path) != digest:
            raise FormatError(f"asset fora do lote foi alterado: {path}")

    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "version_backup": backup,
        "manifest_item_count": len(entries),
        "changed_server_item_count": len(otb_changes),
        "changed_client_item_count": len(dat_changes),
        "before_distribution": dict(sorted(Counter(item["before"] for item in resolved).items())),
        "after_distribution": dict(sorted(Counter(item["after"] for item in resolved).items())),
        "changed_items": [item for item in resolved if item["before"] != item["after"]],
        "transaction_committed": True,
        "untouched_assets_preserved": True,
        "final_validation_passed": final["passed"],
        "warnings": final["warnings"],
        "errors": [],
        "passed": True,
    }
