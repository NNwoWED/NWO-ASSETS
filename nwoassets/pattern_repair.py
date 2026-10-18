from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .appearance_sheet import split_appearance_sheet
from .client import inspect_dat
from .clone_item_importer import _otb_node_ids
from .content import sha256_file
from .errors import FormatError
from .importer import (
    _commit_transaction,
    _remove_if_exists,
    _transaction_path,
    update_otb_sprite_hashes,
    verify_sprite_hash_algorithm,
)
from .otb import inspect_otb, parse_otb_tree
from .otfi import parse_otfi
from .pipeline import inspect_client
from .png import normalize_rgba, read_png_rgba
from .roundtrip import (
    encode_item_appearance,
    scan_dat_record_spans,
    write_dat_item_appearances,
)
from .sprites import RGBA_SIZE, decode_sprite_rgba, read_spr_blocks, sprite_hash
from .versioning import create_version, require_asset_layout


@dataclass(frozen=True)
class PatternRepairEntry:
    sequence: int
    server_id: int
    client_id: int
    source_path: Path
    width: int
    height: int
    layers: int
    pattern_x: int
    pattern_y: int
    pattern_z: int
    frames: int
    frame_duration_ms: int | None
    animation_async: bool


FIELDS = (
    "sequence", "server_id", "client_id", "source_path", "width", "height",
    "layers", "pattern_x", "pattern_y", "pattern_z", "frames",
    "frame_duration_ms", "animation_async",
)


def read_pattern_repair_manifest(path: Path) -> list[PatternRepairEntry]:
    path = path.resolve()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise FormatError(f"{path}: cabecalho esperado: {','.join(FIELDS)}")
        entries: list[PatternRepairEntry] = []
        for row_number, row in enumerate(reader, 2):
            try:
                values = [
                    int(row[name])
                    for name in FIELDS
                    if name not in {"source_path", "frame_duration_ms", "animation_async"}
                ]
                (
                    sequence, server_id, client_id, width, height, layers,
                    pattern_x, pattern_y, pattern_z, frames,
                ) = values
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
            if any(value < 1 or value > 255 for value in (
                width, height, layers, pattern_x, pattern_y, pattern_z, frames
            )):
                raise FormatError(f"{path}:{row_number}: layout deve estar em 1..255")
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
            entries.append(PatternRepairEntry(
                sequence, server_id, client_id, source, width, height, layers,
                pattern_x, pattern_y, pattern_z, frames, duration, async_raw == "1",
            ))
    if not entries or [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError(f"{path}: sequence deve ser continua a partir de 1")
    for field in ("server_id", "client_id", "source_path"):
        values = [getattr(entry, field) for entry in entries]
        if len(values) != len(set(values)):
            raise FormatError(f"{path}: {field} duplicado")
    return entries


def repair_item_patterns(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = True,
    dry_run: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    require_asset_layout(root)
    entries = read_pattern_repair_manifest(manifest_path)
    sprites_root = (root / "sprites").resolve()
    if not all(entry.source_path.is_relative_to(sprites_root) for entry in entries):
        raise FormatError("PNGs devem estar em NWO-ASSETS/sprites")

    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline reprovada: {baseline['errors']}")
    paths = {name: Path(value) for name, value in baseline["paths"].items()}
    otfi = parse_otfi(paths["otfi"])
    hash_gate = verify_sprite_hash_algorithm(paths["dat"], paths["spr"], paths["otb"], otfi)
    if not hash_gate["passed"]:
        raise FormatError("SpriteHash da baseline diverge")

    data = paths["dat"].read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(paths["dat"]))
    items = {span.thing_id: span for span in spans if span.category == "items"}
    _, otb_root = parse_otb_tree(paths["otb"])
    sid_to_cids: dict[int, list[int]] = {}
    for index, node in enumerate(otb_root.children):
        server_id, client_id = _otb_node_ids(node, f"{paths['otb']}:item-{index}")
        if server_id is not None and client_id is not None:
            sid_to_cids.setdefault(server_id, []).append(client_id)
    for entry in entries:
        if sid_to_cids.get(entry.server_id) != [entry.client_id]:
            raise FormatError(
                f"Server ID {entry.server_id} nao aponta exclusivamente para "
                f"Client ID {entry.client_id}: {sid_to_cids.get(entry.server_id)}"
            )
        if entry.client_id not in items:
            raise FormatError(f"Client ID DAT ausente: {entry.client_id}")

    wanted_sprite_ids = {
        sprite_id
        for entry in entries
        for sprite_id in items[entry.client_id].appearances[0].sprite_ids
        if sprite_id
    }
    blocks = read_spr_blocks(paths["spr"], wanted_sprite_ids, otfi)
    rgba_to_sprite_id: dict[bytes, int] = {}
    for sprite_id in sorted(wanted_sprite_ids):
        rgba_to_sprite_id.setdefault(
            decode_sprite_rgba(blocks[sprite_id], transparency=otfi.transparency),
            sprite_id,
        )

    blank = bytes(RGBA_SIZE)
    appearances: dict[int, bytes] = {}
    hashes: dict[int, bytes] = {}
    prepared: list[dict[str, object]] = []
    source_hashes = {str(entry.source_path): sha256_file(entry.source_path) for entry in entries}
    for entry in entries:
        expected_width = otfi.sprite_size * entry.width * entry.layers * entry.pattern_x
        expected_height = (
            otfi.sprite_size * entry.height * entry.frames * entry.pattern_y * entry.pattern_z
        )
        image = normalize_rgba(read_png_rgba(
            entry.source_path, max_width=expected_width, max_height=expected_height
        ))
        groups = split_appearance_sheet(
            image,
            sprite_size=otfi.sprite_size,
            width=entry.width,
            height=entry.height,
            layers=entry.layers,
            pattern_x=entry.pattern_x,
            pattern_y=entry.pattern_y,
            pattern_z=entry.pattern_z,
            frames=entry.frames,
        )
        ordered_tiles = tuple(tile for group in groups for tile in group)
        missing = {tile for tile in ordered_tiles if tile != blank and tile not in rgba_to_sprite_id}
        if missing:
            raise FormatError(
                f"Client ID {entry.client_id}: {len(missing)} pixels nao existem nos sprites "
                "da importacao original; reparo metadata-only recusado"
            )
        sprite_ids = tuple(0 if tile == blank else rgba_to_sprite_id[tile] for tile in ordered_tiles)
        old = items[entry.client_id].appearances[0]
        exact_size = (
            (old.exact_size or otfi.sprite_size)
            if entry.width > 1 or entry.height > 1
            else None
        )
        appearances[entry.client_id] = encode_item_appearance(
            entry.width,
            entry.height,
            entry.frames,
            sprite_ids,
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
        first_hash_tiles = ordered_tiles[: entry.width * entry.height * entry.layers]
        hashes[entry.client_id] = sprite_hash(list(first_hash_tiles))
        prepared.append({
            "sequence": entry.sequence,
            "server_id": entry.server_id,
            "client_id": entry.client_id,
            "source_path": str(entry.source_path),
            "source_sha256": source_hashes[str(entry.source_path)],
            "old_layout": {
                "width": old.width, "height": old.height, "layers": old.layers,
                "pattern_x": old.pattern_x, "pattern_y": old.pattern_y,
                "pattern_z": old.pattern_z, "frames": old.frames,
            },
            "new_layout": {
                "width": entry.width, "height": entry.height, "layers": entry.layers,
                "pattern_x": entry.pattern_x, "pattern_y": entry.pattern_y,
                "pattern_z": entry.pattern_z, "frames": entry.frames,
            },
            "sprite_ids_reused": len({value for value in sprite_ids if value}),
            "sprite_hash": hashes[entry.client_id].hex().upper(),
        })

    common: dict[str, object] = {
        "root": str(root),
        "manifest": str(manifest_path),
        "item_count": len(entries),
        "spr_unchanged": True,
        "items": prepared,
    }
    if dry_run:
        return {**common, "dry_run": True, "passed": True}

    pending = {name: _transaction_path(paths[name], "pending") for name in ("dat", "otb")}
    if any(path.exists() for path in pending.values()):
        raise FormatError("arquivos temporarios de reparo ja existem")
    protected = {
        path: sha256_file(path)
        for path in (root / "assets").rglob("*")
        if path.is_file()
    }
    backup = create_version(root)
    try:
        write_dat_item_appearances(paths["dat"], pending["dat"], otfi, appearances)
        update_otb_sprite_hashes(
            paths["otb"], pending["otb"], hashes,
            animated={entry.client_id: entry.frames > 1 for entry in entries},
        )
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
            if span.category == "items" and span.thing_id in appearances:
                if data[span.start:span.properties_end] != staged_data[staged.start:staged.properties_end]:
                    raise FormatError(f"Client ID {span.thing_id}: propriedades DAT mudaram")
                if staged_data[staged.properties_end:staged.end] != appearances[span.thing_id]:
                    raise FormatError(f"Client ID {span.thing_id}: layout DAT nao persistiu")
            elif data[span.start:span.end] != staged_data[staged.start:staged.end]:
                raise FormatError(f"registro DAT fora do alvo mudou: {span.category} {span.thing_id}")
        if protected != {path: sha256_file(path) for path in protected}:
            raise FormatError("baseline mudou durante a preparacao")
        if source_hashes != {str(entry.source_path): sha256_file(entry.source_path) for entry in entries}:
            raise FormatError("PNG de origem mudou durante a preparacao")
        final = _commit_transaction(
            root,
            {paths["dat"]: pending["dat"], paths["otb"]: pending["otb"]},
            deep_spr=deep_spr,
        )
    except BaseException:
        _remove_if_exists(list(pending.values()))
        raise
    if not final["passed"]:
        raise FormatError("validacao final falhou")
    for path, digest in protected.items():
        if path not in {paths["dat"], paths["otb"]} and sha256_file(path) != digest:
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
