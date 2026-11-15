from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
import struct

from .atomic import atomic_binary_output
from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import _commit_transaction, _remove_if_exists, _transaction_path
from .otfi import parse_otfi
from .pipeline import inspect_client
from .properties import read_otb_items
from .roundtrip import _dat_property_chunks, scan_dat_record_spans
from .versioning import create_version, require_asset_layout


DAT_LIGHT_FLAG = 0x15


@dataclass(frozen=True)
class LightEdit:
    sequence: int
    server_id: int
    client_id: int
    light_color: int


def read_light_manifest(path: Path) -> list[LightEdit]:
    if not path.is_file():
        raise FormatError(f"manifesto de luz nao encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"sequence", "server_id", "client_id", "light_color"}
        if set(reader.fieldnames or ()) != expected:
            raise FormatError(f"manifesto exige exatamente as colunas {sorted(expected)}")
        entries: list[LightEdit] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                entry = LightEdit(
                    sequence=int(row["sequence"]),
                    server_id=int(row["server_id"]),
                    client_id=int(row["client_id"]),
                    light_color=int(row["light_color"]),
                )
            except (TypeError, ValueError) as exc:
                raise FormatError(f"linha {row_number}: valor numerico invalido") from exc
            if not 1 <= entry.light_color <= 215:
                raise FormatError(f"linha {row_number}: light_color fora de 1..215")
            entries.append(entry)
    if not entries:
        raise FormatError("manifesto de luz esta vazio")
    if [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError("sequence deve iniciar em 1 e ser continua")
    if len({entry.server_id for entry in entries}) != len(entries):
        raise FormatError("manifesto contem Server IDs duplicados")
    targets: dict[int, int] = {}
    for entry in entries:
        previous = targets.setdefault(entry.client_id, entry.light_color)
        if previous != entry.light_color:
            raise FormatError(f"Client ID {entry.client_id} recebeu cores conflitantes")
    return entries


def read_dat_lights(data: bytes, otfi, source: str) -> dict[int, tuple[int, int]]:
    result: dict[int, tuple[int, int]] = {}
    for span in scan_dat_record_spans(data, otfi, source):
        if span.category != "items":
            continue
        chunks = [
            chunk
            for flag, chunk in _dat_property_chunks(data, span, source)
            if flag == DAT_LIGHT_FLAG
        ]
        if not chunks:
            continue
        if len(chunks) != 1 or len(chunks[0]) != 5:
            raise FormatError(f"{source}: luz DAT invalida no item {span.thing_id}")
        result[span.thing_id] = struct.unpack("<HH", chunks[0][1:])
    return result


def write_dat_light_colors(
    source: Path, destination: Path, otfi, edits: dict[int, int]
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
    for client_id, light_color in edits.items():
        chunks = _dat_property_chunks(data, items[client_id], str(source))
        found = [chunk for flag, chunk in chunks if flag == DAT_LIGHT_FLAG]
        if len(found) != 1 or len(found[0]) != 5:
            raise FormatError(f"Client ID {client_id} nao possui luz DAT unica")
        intensity, before_color = struct.unpack("<HH", found[0][1:])
        replacements[client_id] = b"".join(
            bytes((flag,)) + struct.pack("<HH", intensity, light_color)
            if flag == DAT_LIGHT_FLAG
            else chunk
            for flag, chunk in chunks
        ) + b"\xFF"
        changes[client_id] = {
            "intensity": intensity,
            "before_color": before_color,
            "after_color": light_color,
        }

    with atomic_binary_output(destination) as output:
        output.write(data[:12])
        for span in spans:
            if span.category == "items" and span.thing_id in replacements:
                output.write(replacements[span.thing_id])
                output.write(data[span.properties_end : span.end])
            else:
                output.write(data[span.start : span.end])
    return changes


def edit_item_light_colors(
    root: Path, manifest_path: Path, *, deep_spr: bool = False
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    require_asset_layout(root)
    entries = read_light_manifest(manifest_path)
    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline de origem reprovou: {baseline['errors']}")
    paths = {name: Path(value) for name, value in baseline["paths"].items()}
    otfi = parse_otfi(paths["otfi"])
    current = read_dat_lights(paths["dat"].read_bytes(), otfi, str(paths["dat"]))
    otb_items = read_otb_items(paths["otb"])
    by_client: dict[int, list[int]] = {}
    for server_id, item in otb_items.items():
        by_client.setdefault(item["client_id"], []).append(server_id)

    targets: dict[int, int] = {}
    resolved: list[dict[str, int]] = []
    for entry in entries:
        item = otb_items.get(entry.server_id)
        if item is None:
            raise FormatError(f"Server ID {entry.server_id} inexistente no OTB")
        if item["client_id"] != entry.client_id:
            raise FormatError(
                f"Server ID {entry.server_id}: manifesto informa Client ID "
                f"{entry.client_id}, mas o OTB mapeia {item['client_id']}"
            )
        if by_client[entry.client_id] != [entry.server_id]:
            raise FormatError(
                f"Client ID {entry.client_id} possui vinculo OTB ambiguo: "
                f"{by_client[entry.client_id]}"
            )
        if entry.client_id not in current:
            raise FormatError(f"Client ID {entry.client_id} nao possui luz no DAT")
        intensity, before_color = current[entry.client_id]
        targets[entry.client_id] = entry.light_color
        resolved.append({
            "sequence": entry.sequence,
            "server_id": entry.server_id,
            "client_id": entry.client_id,
            "intensity": intensity,
            "before_color": before_color,
            "after_color": entry.light_color,
        })
    changed = {
        client_id: color
        for client_id, color in targets.items()
        if current[client_id][1] != color
    }
    if not changed:
        raise FormatError("o manifesto nao produz nenhuma alteracao na baseline atual")

    pending = _transaction_path(paths["dat"], "pending")
    if pending.exists():
        raise FormatError(f"arquivo temporario ja existe: {pending}")
    protected = {
        path: sha256_file(path)
        for path in (root / "assets").rglob("*")
        if path.is_file()
    }
    backup = create_version(root)
    try:
        changes = write_dat_light_colors(paths["dat"], pending, otfi, changed)
        spr = inspect_spr(paths["spr"], otfi, deep=deep_spr)
        inspect_dat(
            pending,
            otfi,
            expected_metadata_reader=int(baseline["profile"]["metadata_reader"]),
            sprite_count=int(spr["sprite_count"]),
        )
        after = read_dat_lights(pending.read_bytes(), otfi, str(pending))
        for client_id, color in changed.items():
            if after.get(client_id) != (current[client_id][0], color):
                raise FormatError(f"validacao DAT divergiu no Client ID {client_id}")
        if {path: sha256_file(path) for path in protected} != protected:
            raise FormatError("um asset oficial mudou durante a preparacao")
        final = _commit_transaction(root, {paths["dat"]: pending}, deep_spr=deep_spr)
    except BaseException:
        _remove_if_exists([pending])
        raise
    for path, digest in protected.items():
        if path != paths["dat"] and sha256_file(path) != digest:
            raise FormatError(f"asset fora do lote foi alterado: {path}")
    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "version_backup": backup,
        "item_count": len(changes),
        "changed_items": resolved,
        "transaction_committed": True,
        "intensities_preserved": True,
        "untouched_assets_preserved": True,
        "final_validation_passed": final["passed"],
        "warnings": final["warnings"],
        "errors": [],
        "passed": True,
    }
