from __future__ import annotations

from pathlib import Path
import csv

from .client import inspect_dat
from .content import sha256_file
from .errors import FormatError
from .importer import _commit_transaction, _remove_if_exists, _transaction_path
from .otfi import parse_otfi
from .pipeline import inspect_client
from .roundtrip import (
    read_dat_animation_timings,
    scan_dat_record_spans,
    write_dat_animation_durations,
)
from .versioning import create_version, require_asset_layout


def read_animation_manifest(
    path: Path,
) -> tuple[str, dict[int, tuple[int, ...]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"sequence", "category", "client_id", "frame_durations_ms"}
            missing = required - set(reader.fieldnames or ())
            if missing:
                raise FormatError(
                    f"{path}: colunas ausentes no manifesto: {', '.join(sorted(missing))}"
                )
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FormatError(f"{path}: nao foi possivel ler o manifesto: {exc}") from exc
    if not rows:
        raise FormatError(f"{path}: manifesto vazio")

    categories: set[str] = set()
    edits: dict[int, tuple[int, ...]] = {}
    sequences: list[int] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            sequence = int(row["sequence"])
            client_id = int(row["client_id"])
            durations = tuple(
                int(value.strip())
                for value in (row["frame_durations_ms"] or "").split("|")
                if value.strip()
            )
        except (TypeError, ValueError) as exc:
            raise FormatError(f"{path}:{row_number}: valor numerico invalido") from exc
        category = (row["category"] or "").strip().casefold()
        if category not in {"items", "effects", "missiles"}:
            raise FormatError(f"{path}:{row_number}: categoria invalida: {category}")
        if not durations:
            raise FormatError(f"{path}:{row_number}: frame_durations_ms vazio")
        if client_id in edits:
            raise FormatError(f"{path}: Client ID duplicado: {client_id}")
        sequences.append(sequence)
        categories.add(category)
        edits[client_id] = durations

    expected = list(range(1, len(rows) + 1))
    if sequences != expected:
        raise FormatError(f"{path}: sequence deve ser continua e ordenada")
    if len(categories) != 1:
        raise FormatError(f"{path}: um manifesto deve usar somente uma categoria")
    return categories.pop(), edits


def _edit_animation_durations_impl(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    layout = require_asset_layout(root)
    category, edits = read_animation_manifest(manifest_path)
    source_report = inspect_client(root, deep_spr=deep_spr)
    if not source_report["passed"]:
        raise FormatError(f"baseline de origem reprovou: {source_report['errors']}")
    paths = {name: Path(value) for name, value in source_report["paths"].items()}
    maps = sorted(layout["world"].glob("*.otbm"))
    if len(maps) != 1:
        raise FormatError(f"esperado um mapa canonico; encontrados {len(maps)}")
    protected = {**paths, "otbm": maps[0]}
    source_hashes = {name: sha256_file(path) for name, path in protected.items()}
    otfi = parse_otfi(paths["otfi"])
    source_data = paths["dat"].read_bytes()
    source_spans = scan_dat_record_spans(source_data, otfi, str(paths["dat"]))
    source_timings = read_dat_animation_timings(
        source_data, otfi, category, set(edits), str(paths["dat"])
    )

    pending = _transaction_path(paths["dat"], "pending")
    if pending.exists():
        raise FormatError(f"arquivo temporario de importacao ja existe: {pending}")
    backup = create_version(root)
    try:
        changes = write_dat_animation_durations(
            paths["dat"], pending, otfi, category, edits
        )
        inspect_dat(
            pending,
            otfi,
            expected_metadata_reader=int(source_report["profile"]["metadata_reader"]),
            sprite_count=int(source_report["spr"]["sprite_count"]),
        )
        pending_data = pending.read_bytes()
        pending_spans = scan_dat_record_spans(pending_data, otfi, str(pending))
        if len(source_spans) != len(pending_spans):
            raise FormatError("quantidade de registros DAT mudou")
        target_keys = {(category, thing_id) for thing_id in edits}
        for source_span, pending_span in zip(source_spans, pending_spans):
            identity = (source_span.category, source_span.thing_id)
            if identity != (pending_span.category, pending_span.thing_id):
                raise FormatError("ordem de registros DAT mudou")
            if identity not in target_keys:
                if source_data[source_span.start : source_span.end] != pending_data[
                    pending_span.start : pending_span.end
                ]:
                    raise FormatError(f"registro DAT nao alvo mudou em {identity}")
            else:
                if source_data[source_span.start : source_span.properties_end] != pending_data[
                    pending_span.start : pending_span.properties_end
                ]:
                    raise FormatError(f"propriedades DAT mudaram em {identity}")
                if source_span.appearances != pending_span.appearances:
                    raise FormatError(f"aparencia ou Sprite IDs mudaram em {identity}")

        pending_timings = read_dat_animation_timings(
            pending_data, otfi, category, set(edits), str(pending)
        )
        for thing_id, durations in edits.items():
            expected = tuple((duration, duration) for duration in durations)
            if pending_timings[thing_id].durations != expected:
                raise FormatError(f"duracoes nao persistiram no Client ID {thing_id}")
            source_timing = source_timings[thing_id]
            pending_timing = pending_timings[thing_id]
            if (
                source_timing.animation_async != pending_timing.animation_async
                or source_timing.loop_count != pending_timing.loop_count
                or source_timing.start_frame != pending_timing.start_frame
            ):
                raise FormatError(f"metadados da animacao mudaram no Client ID {thing_id}")

        if source_hashes != {name: sha256_file(path) for name, path in protected.items()}:
            raise FormatError("um arquivo de origem mudou durante a operacao")
        final_report = _commit_transaction(
            root, {paths["dat"]: pending}, deep_spr=deep_spr
        )
    except BaseException:
        _remove_if_exists([pending])
        raise

    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "category": category,
        "version_backup": backup,
        "changes": {str(key): value for key, value in changes.items()},
        "dat_sha256": sha256_file(paths["dat"]),
        "spr_unchanged": source_hashes["spr"] == sha256_file(paths["spr"]),
        "otb_unchanged": source_hashes["otb"] == sha256_file(paths["otb"]),
        "map_unchanged": source_hashes["otbm"] == sha256_file(maps[0]),
        "final_validation_passed": final_report["passed"],
        "warnings": final_report["warnings"],
        "errors": [],
        "passed": True,
    }


def edit_animation_durations(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    try:
        return _edit_animation_durations_impl(
            root, manifest_path, deep_spr=deep_spr
        )
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
