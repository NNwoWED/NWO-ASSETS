from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
import struct

from .client import FLAG_NAMES_860, _NO_PAYLOAD, inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import _commit_transaction, _remove_if_exists, _transaction_path
from .otb import OtbNode, inspect_otb, parse_otb_tree
from .otfi import parse_otfi
from .pipeline import inspect_client
from .roundtrip import dat_item_flags, write_dat_item_flags, write_otb_document
from .versioning import create_version, require_asset_layout


OTB_FLAG_NAMES = {
    0: "block_solid",
    1: "block_projectile",
    2: "block_pathfind",
    3: "has_height",
    4: "usable",
    5: "pickupable",
    6: "movable",
    7: "stackable",
    8: "floor_change_down",
    9: "floor_change_north",
    10: "floor_change_east",
    11: "floor_change_south",
    12: "floor_change_west",
    13: "always_on_top",
    14: "readable",
    15: "rotatable",
    16: "hangable",
    17: "vertical",
    18: "horizontal",
    19: "cannot_decay",
    20: "allow_distance_read",
    21: "unused",
    22: "client_charges",
    23: "look_through",
    24: "animation",
    25: "walk_stack",
    26: "force_use",
    27: "walkable_water",
}
OTB_FLAG_VALUES = {name: 1 << bit for bit, name in OTB_FLAG_NAMES.items()}
DAT_FLAG_VALUES = {name: value for value, name in FLAG_NAMES_860.items() if value in _NO_PAYLOAD}


@dataclass(frozen=True)
class PropertyEdit:
    sequence: int
    server_id: int
    client_id: int | None
    dat_add: frozenset[int]
    dat_remove: frozenset[int]
    otb_add: int
    otb_remove: int


def _parse_names(value: str, known: dict[str, int], field: str, row: int) -> set[int]:
    names = {part.strip().lower() for part in value.replace(",", "|").split("|") if part.strip()}
    unknown = sorted(names - set(known))
    if unknown:
        raise FormatError(f"linha {row}: {field} contém flags desconhecidas: {unknown}")
    return {known[name] for name in names}


def read_property_manifest(path: Path) -> list[PropertyEdit]:
    if not path.is_file():
        raise FormatError(f"manifesto de propriedades não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"sequence", "server_id"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise FormatError("manifesto exige as colunas sequence e server_id")
        entries: list[PropertyEdit] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                sequence = int(row["sequence"])
                server_id = int(row["server_id"])
                raw_client = (row.get("client_id") or "").strip()
                client_id = int(raw_client) if raw_client else None
            except (TypeError, ValueError) as exc:
                raise FormatError(f"linha {row_number}: IDs ou sequência inválidos") from exc
            dat_add = _parse_names(row.get("dat_add_flags") or "", DAT_FLAG_VALUES, "dat_add_flags", row_number)
            dat_remove = _parse_names(row.get("dat_remove_flags") or "", DAT_FLAG_VALUES, "dat_remove_flags", row_number)
            otb_add_values = _parse_names(row.get("otb_add_flags") or "", OTB_FLAG_VALUES, "otb_add_flags", row_number)
            otb_remove_values = _parse_names(row.get("otb_remove_flags") or "", OTB_FLAG_VALUES, "otb_remove_flags", row_number)
            if dat_add & dat_remove or otb_add_values & otb_remove_values:
                raise FormatError(f"linha {row_number}: a mesma flag não pode ser adicionada e removida")
            if not (dat_add or dat_remove or otb_add_values or otb_remove_values):
                raise FormatError(f"linha {row_number}: nenhuma alteração declarada")
            entries.append(PropertyEdit(
                sequence, server_id, client_id, frozenset(dat_add), frozenset(dat_remove),
                sum(otb_add_values), sum(otb_remove_values),
            ))
    if not entries:
        raise FormatError("manifesto de propriedades está vazio")
    if [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError("sequence deve ser contínua, iniciar em 1 e seguir a ordem do CSV")
    server_ids = [entry.server_id for entry in entries]
    if len(server_ids) != len(set(server_ids)):
        raise FormatError("manifesto contém Server IDs duplicados")
    return entries


def _node_attributes(node: OtbNode, source: str) -> tuple[int, int, int | None, int | None]:
    if len(node.data) < 5:
        raise FormatError(f"{source}: nó de item OTB truncado")
    group = node.data[0]
    flags = struct.unpack_from("<I", node.data, 1)[0]
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
        if attribute in {0x10, 0x11} and length == 2:
            value = struct.unpack_from("<H", node.data, position)[0]
            if attribute == 0x10:
                server_id = value
            else:
                client_id = value
        position += length
    return group, flags, server_id, client_id


def read_otb_items(path: Path) -> dict[int, dict[str, int]]:
    _, root = parse_otb_tree(path)
    result: dict[int, dict[str, int]] = {}
    for index, node in enumerate(root.children):
        group, flags, server_id, client_id = _node_attributes(node, f"{path}:item-{index}")
        if server_id is None:
            continue
        if server_id in result:
            raise FormatError(f"{path}: Server ID OTB duplicado: {server_id}")
        result[server_id] = {
            "group": group,
            "flags": flags,
            "client_id": client_id if client_id is not None else 0,
        }
    return result


def flag_names(mask: int) -> list[str]:
    names = [name for bit, name in OTB_FLAG_NAMES.items() if mask & (1 << bit)]
    unknown = mask & ~sum(1 << bit for bit in OTB_FLAG_NAMES)
    if unknown:
        names.append(f"unknown_0x{unknown:08X}")
    return names


def dat_flag_names(values: tuple[int, ...] | list[int]) -> list[str]:
    return [FLAG_NAMES_860.get(value, f"0x{value:02X}") for value in values]


def write_otb_item_flags(
    source: Path, destination: Path, edits: dict[int, tuple[int, int]]
) -> dict[int, dict[str, int]]:
    if source.resolve() == destination.resolve() or destination.exists():
        raise FormatError("destino OTB temporário inválido ou já existente")
    file_version, root = parse_otb_tree(source)
    found: dict[int, dict[str, int]] = {}
    new_children: list[OtbNode] = []
    for index, node in enumerate(root.children):
        _, before, server_id, _ = _node_attributes(node, f"{source}:item-{index}")
        if server_id is None or server_id not in edits:
            new_children.append(node)
            continue
        add, remove = edits[server_id]
        after = (before | add) & ~remove
        new_data = node.data[:1] + struct.pack("<I", after) + node.data[5:]
        new_children.append(OtbNode(new_data, node.children))
        found[server_id] = {"before": before, "after": after}
    missing = sorted(set(edits) - set(found))
    if missing:
        raise FormatError(f"Server IDs OTB inexistentes: {missing}")
    write_otb_document(file_version, OtbNode(root.data, new_children), destination)
    return found


def edit_item_properties(
    root: Path, manifest_path: Path, *, deep_spr: bool = False
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    require_asset_layout(root)
    entries = read_property_manifest(manifest_path)
    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline de origem reprovou: {baseline['errors']}")
    paths = {name: Path(value) for name, value in baseline["paths"].items()}
    otfi = parse_otfi(paths["otfi"])
    otb_items = read_otb_items(paths["otb"])
    source_dat = paths["dat"].read_bytes()
    current_dat = dat_item_flags(source_dat, otfi, str(paths["dat"]))

    dat_edits: dict[int, tuple[set[int], set[int]]] = {}
    otb_edits: dict[int, tuple[int, int]] = {}
    resolved: list[dict[str, object]] = []
    for entry in entries:
        item = otb_items.get(entry.server_id)
        if item is None:
            raise FormatError(f"Server ID {entry.server_id} não existe no OTB")
        client_id = item["client_id"]
        if client_id == 0:
            raise FormatError(f"Server ID {entry.server_id} não possui Client ID no OTB")
        if entry.client_id is not None and entry.client_id != client_id:
            raise FormatError(
                f"Server ID {entry.server_id}: manifesto informa Client ID {entry.client_id}, "
                f"mas o OTB mapeia {client_id}"
            )
        if client_id not in current_dat:
            raise FormatError(f"Client ID {client_id} não existe no DAT")
        if entry.dat_add or entry.dat_remove:
            previous_add, previous_remove = dat_edits.get(client_id, (set(), set()))
            combined_add = previous_add | set(entry.dat_add)
            combined_remove = previous_remove | set(entry.dat_remove)
            if combined_add & combined_remove:
                raise FormatError(
                    f"Client ID {client_id}: alterações DAT conflitantes entre linhas"
                )
            dat_edits[client_id] = (combined_add, combined_remove)
        if entry.otb_add or entry.otb_remove:
            otb_edits[entry.server_id] = (entry.otb_add, entry.otb_remove)
        resolved.append({"sequence": entry.sequence, "server_id": entry.server_id, "client_id": client_id})

    dat_will_change = any(
        ((set(current_dat[client_id]) | add) - remove) != set(current_dat[client_id])
        for client_id, (add, remove) in dat_edits.items()
    )
    otb_will_change = any(
        ((otb_items[server_id]["flags"] | add) & ~remove)
        != otb_items[server_id]["flags"]
        for server_id, (add, remove) in otb_edits.items()
    )
    if not (dat_will_change or otb_will_change):
        raise FormatError("o manifesto não produz nenhuma alteração na baseline atual")

    target_dat = _transaction_path(paths["dat"], "pending")
    target_otb = _transaction_path(paths["otb"], "pending")
    targets: dict[Path, Path] = {}
    if dat_will_change:
        targets[paths["dat"]] = target_dat
    if otb_will_change:
        targets[paths["otb"]] = target_otb
    stale = [str(path) for path in targets.values() if path.exists()]
    if stale:
        raise FormatError(f"arquivos temporários já existem: {stale}")

    protected = {
        path: sha256_file(path)
        for path in (root / "assets").rglob("*")
        if path.is_file()
    }
    backup = create_version(root)
    try:
        if dat_will_change:
            dat_changes = write_dat_item_flags(paths["dat"], target_dat, otfi, dat_edits)
        else:
            dat_changes = {}
        if otb_will_change:
            otb_changes = write_otb_item_flags(paths["otb"], target_otb, otb_edits)
        else:
            otb_changes = {}

        pending_spr = inspect_spr(paths["spr"], otfi, deep=deep_spr)
        inspect_dat(
            target_dat if dat_will_change else paths["dat"], otfi,
            expected_metadata_reader=int(baseline["profile"]["metadata_reader"]),
            sprite_count=int(pending_spr["sprite_count"]),
        )
        pending_otb = inspect_otb(target_otb if otb_will_change else paths["otb"])
        if pending_otb["malformed_attributes"]:
            raise FormatError("OTB preparado possui atributos malformados")
        dat_to_validate = target_dat if dat_will_change else paths["dat"]
        after_dat = dat_item_flags(dat_to_validate.read_bytes(), otfi, str(dat_to_validate))
        for client_id, change in dat_changes.items():
            if after_dat[client_id] != change["after"]:
                raise FormatError(f"validação DAT divergiu no Client ID {client_id}")
    except BaseException:
        _remove_if_exists(list(targets.values()))
        raise

    before_commit = {path: sha256_file(path) for path in protected}
    if before_commit != protected:
        _remove_if_exists(list(targets.values()))
        raise FormatError("um asset oficial mudou durante a preparação")
    final = _commit_transaction(root, targets, deep_spr=deep_spr)
    changed_paths = set(targets)
    for path, digest in protected.items():
        if path not in changed_paths and sha256_file(path) != digest:
            raise FormatError(f"asset fora do lote foi alterado: {path}")

    details = []
    for item in resolved:
        server_id = int(item["server_id"])
        client_id = int(item["client_id"])
        dat_change = dat_changes.get(client_id)
        otb_change = otb_changes.get(server_id)
        details.append({
            **item,
            "dat": None if dat_change is None else {
                "before": dat_flag_names(dat_change["before"]),
                "after": dat_flag_names(dat_change["after"]),
            },
            "otb": None if otb_change is None else {
                "before_mask": f"0x{otb_change['before']:08X}",
                "after_mask": f"0x{otb_change['after']:08X}",
                "before": flag_names(otb_change["before"]),
                "after": flag_names(otb_change["after"]),
            },
        })
    return {
        "root": str(root), "manifest": str(manifest_path), "version_backup": backup,
        "item_count": len(details), "items": details, "transaction_committed": True,
        "untouched_assets_preserved": True, "final_validation_passed": final["passed"],
        "warnings": final["warnings"], "errors": [], "passed": True,
    }
