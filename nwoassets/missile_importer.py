from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import csv
import hashlib

from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import (
    _commit_transaction,
    _remove_if_exists,
    _sha256_segment,
    _transaction_path,
)
from .otfi import parse_otfi
from .outfit_importer import split_outfit_sheet
from .pipeline import inspect_client
from .png import normalize_rgba, read_png_rgba
from .roundtrip import (
    append_spr_blocks,
    encode_item_appearance,
    scan_dat_record_spans,
    write_dat_appearances,
)
from .sprites import RGBA_SIZE, decode_sprite_rgba, encode_sprite_rgba, read_spr_blocks
from .versioning import create_version, require_asset_layout


@dataclass(frozen=True)
class MissileManifestEntry:
    sequence: int
    operation: str
    missile_id: int
    reference_missile_id: int
    source_path: Path
    frames: int
    frame_duration_ms: int
    animation_async: bool


@dataclass(frozen=True)
class PreparedMissile:
    sequence: int
    operation: str
    missile_id: int
    reference_missile_id: int
    source_path: str
    file_sha256: str
    pixels_sha256: str
    image_width: int
    image_height: int
    width_tiles: int
    height_tiles: int
    pattern_x: int
    pattern_y: int
    pattern_z: int
    frames: int
    frame_duration_ms: int
    animation_async: bool
    sprite_ids: tuple[int, ...]


def read_missile_manifest(path: Path) -> list[MissileManifestEntry]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {
                "sequence",
                "operation",
                "missile_id",
                "reference_missile_id",
                "source_path",
                "frames",
                "frame_duration_ms",
            }
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

    entries: list[MissileManifestEntry] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            sequence = int(row["sequence"])
            missile_id = int(row["missile_id"])
            reference_missile_id = int(row["reference_missile_id"])
            frames = int(row["frames"])
            frame_duration_ms = int(row["frame_duration_ms"])
        except (TypeError, ValueError) as exc:
            raise FormatError(f"{path}:{row_number}: valor numerico invalido") from exc
        operation = (row.get("operation") or "").strip().casefold()
        if operation not in {"reserved", "replace"}:
            raise FormatError(
                f"{path}:{row_number}: operation deve ser reserved ou replace"
            )
        if missile_id == reference_missile_id and operation != "replace":
            raise FormatError(
                f"{path}:{row_number}: alvo e referencia iguais exigem operation=replace"
            )
        if not 1 <= frames <= 255:
            raise FormatError(f"{path}:{row_number}: frames deve estar entre 1 e 255")
        if not 1 <= frame_duration_ms <= 0xFFFFFFFF:
            raise FormatError(f"{path}:{row_number}: frame_duration_ms invalido")
        raw_async = (row.get("animation_async") or "0").strip()
        if raw_async not in {"0", "1"}:
            raise FormatError(f"{path}:{row_number}: animation_async deve ser 0 ou 1")
        raw_source = (row.get("source_path") or "").strip()
        if not raw_source:
            raise FormatError(f"{path}:{row_number}: source_path vazio")
        source = Path(raw_source)
        if not source.is_absolute():
            source = path.parent / source
        source = source.resolve()
        if source.suffix.casefold() != ".png" or not source.is_file():
            raise FormatError(f"{path}:{row_number}: PNG nao encontrado: {source}")
        entries.append(
            MissileManifestEntry(
                sequence,
                operation,
                missile_id,
                reference_missile_id,
                source,
                frames,
                frame_duration_ms,
                raw_async == "1",
            )
        )

    if [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError(f"{path}: sequence deve ser continua e ordenada")
    target_ids = [entry.missile_id for entry in entries]
    if len(set(target_ids)) != len(target_ids):
        raise FormatError(f"{path}: Missile IDs alvo duplicados")
    return entries


def _import_missiles_impl(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    layout = require_asset_layout(root)
    entries = read_missile_manifest(manifest_path)
    source_report = inspect_client(root, deep_spr=deep_spr)
    if not source_report["passed"]:
        raise FormatError(f"baseline de origem reprovou: {source_report['errors']}")
    paths = {name: Path(value) for name, value in source_report["paths"].items()}
    maps = sorted(layout["world"].glob("*.otbm"))
    if len(maps) != 1:
        raise FormatError(f"esperado um mapa canonico; encontrados {len(maps)}")
    protected_sources = {**paths, "otbm": maps[0]}
    protected_untouched = {
        "otfi": paths["otfi"],
        "otb": paths["otb"],
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
    max_missile_id = int(source_report["dat"]["max_ids"]["missiles"])
    all_ids = [
        value
        for entry in entries
        for value in (entry.missile_id, entry.reference_missile_id)
    ]
    invalid_ids = sorted({value for value in all_ids if value < 1 or value > max_missile_id})
    if invalid_ids:
        raise FormatError(f"Missile IDs fora da faixa 1..{max_missile_id}: {invalid_ids}")

    source_data = paths["dat"].read_bytes()
    source_spans = scan_dat_record_spans(source_data, otfi, str(paths["dat"]))
    source_missiles = {
        span.thing_id: span for span in source_spans if span.category == "missiles"
    }
    for entry in entries:
        target = source_missiles[entry.missile_id]
        reference = source_missiles[entry.reference_missile_id]
        target_has_sprites = any(
            any(appearance.sprite_ids) for appearance in target.appearances
        )
        if entry.operation == "reserved" and target_has_sprites:
            raise FormatError(f"Missile ID reservado {entry.missile_id} nao esta vazio")
        if entry.operation == "replace" and not target_has_sprites:
            raise FormatError(f"Missile ID para replace {entry.missile_id} esta vazio")
        if len(reference.appearances) != 1:
            raise FormatError(
                f"Missile de referencia {entry.reference_missile_id} possui frame groups"
            )
        if not any(reference.appearances[0].sprite_ids):
            raise FormatError(
                f"Missile de referencia {entry.reference_missile_id} esta vazio"
            )

    old_sprite_count = int(source_report["spr"]["sprite_count"])
    next_sprite_id = old_sprite_count + 1
    blank_tile = bytes(RGBA_SIZE)
    blocks: list[bytes] = []
    expected_tiles: dict[int, bytes] = {}
    replacements: dict[int, bytes] = {}
    prepared: list[PreparedMissile] = []

    for entry in entries:
        reference = source_missiles[entry.reference_missile_id].appearances[0]
        appearance = replace(reference, frames=entry.frames, sprite_ids=())
        expected_width = (
            otfi.sprite_size * appearance.width * appearance.layers * appearance.pattern_x
        )
        expected_height = (
            otfi.sprite_size
            * appearance.height
            * appearance.frames
            * appearance.pattern_y
            * appearance.pattern_z
        )
        image = normalize_rgba(
            read_png_rgba(
                entry.source_path,
                max_width=expected_width,
                max_height=expected_height,
            )
        )
        tiles = split_outfit_sheet(image, (appearance,), otfi.sprite_size)[0]
        sprite_ids: list[int] = []
        for tile in tiles:
            if tile == blank_tile:
                sprite_ids.append(0)
                continue
            sprite_id = next_sprite_id
            next_sprite_id += 1
            sprite_ids.append(sprite_id)
            blocks.append(encode_sprite_rgba(tile))
            expected_tiles[sprite_id] = tile
        replacements[entry.missile_id] = encode_item_appearance(
            appearance.width,
            appearance.height,
            appearance.frames,
            tuple(sprite_ids),
            otfi,
            frame_duration_ms=(entry.frame_duration_ms if entry.frames > 1 else None),
            animation_async=entry.animation_async,
            exact_size=appearance.exact_size,
            allow_zero_sprite_ids=True,
            layers=appearance.layers,
            pattern_x=appearance.pattern_x,
            pattern_y=appearance.pattern_y,
            pattern_z=appearance.pattern_z,
        )
        prepared.append(
            PreparedMissile(
                sequence=entry.sequence,
                operation=entry.operation,
                missile_id=entry.missile_id,
                reference_missile_id=entry.reference_missile_id,
                source_path=str(entry.source_path),
                file_sha256=sha256_file(entry.source_path),
                pixels_sha256=hashlib.sha256(image.rgba).hexdigest().upper(),
                image_width=image.width,
                image_height=image.height,
                width_tiles=appearance.width,
                height_tiles=appearance.height,
                pattern_x=appearance.pattern_x,
                pattern_y=appearance.pattern_y,
                pattern_z=appearance.pattern_z,
                frames=appearance.frames,
                frame_duration_ms=entry.frame_duration_ms,
                animation_async=entry.animation_async,
                sprite_ids=tuple(sprite_ids),
            )
        )

    targets = {
        name: _transaction_path(paths[name], "pending") for name in ("dat", "spr")
    }
    stale = [str(path) for path in targets.values() if path.exists()]
    if stale:
        raise FormatError(f"arquivos temporarios de importacao ja existem: {stale}")
    backup = create_version(root)

    def abort_pending(message: str) -> None:
        _remove_if_exists(list(targets.values()))
        raise FormatError(message)

    try:
        append_spr_blocks(paths["spr"], targets["spr"], otfi, blocks)
        write_dat_appearances(
            paths["dat"], targets["dat"], otfi, "missiles", replacements
        )
        pending_spr = inspect_spr(targets["spr"], otfi, deep=deep_spr)
        pending_dat = inspect_dat(
            targets["dat"],
            otfi,
            expected_metadata_reader=int(source_report["profile"]["metadata_reader"]),
            sprite_count=int(pending_spr["sprite_count"]),
        )
    except BaseException:
        _remove_if_exists(list(targets.values()))
        raise

    expected_sprite_count = old_sprite_count + len(blocks)
    if int(pending_spr["sprite_count"]) != expected_sprite_count:
        abort_pending("count SPR preparado diverge do lote")
    if int(pending_dat["appearance"]["max_referenced_sprite_id"]) > expected_sprite_count:
        abort_pending("DAT preparado referencia Sprite ID fora do novo SPR")

    source_table_end = int(source_report["spr"]["table_end"])
    staged_table_end = int(pending_spr["table_end"])
    old_body_size = paths["spr"].stat().st_size - source_table_end
    if _sha256_segment(paths["spr"], source_table_end) != _sha256_segment(
        targets["spr"], staged_table_end, old_body_size
    ):
        abort_pending("payload dos sprites antigos mudou durante a importacao")

    staged_data = targets["dat"].read_bytes()
    staged_spans = scan_dat_record_spans(staged_data, otfi, str(targets["dat"]))
    if source_data[:12] != staged_data[:12] or len(source_spans) != len(staged_spans):
        abort_pending("estrutura DAT mudou durante a importacao")
    target_keys = {("missiles", missile_id) for missile_id in replacements}
    for source_span, staged_span in zip(source_spans, staged_spans):
        identity = (source_span.category, source_span.thing_id)
        if identity != (staged_span.category, staged_span.thing_id):
            abort_pending("ordem de registros DAT mudou durante a importacao")
        if source_data[source_span.start : source_span.properties_end] != staged_data[
            staged_span.start : staged_span.properties_end
        ]:
            abort_pending(f"propriedades DAT mudaram em {identity}")
        if identity not in target_keys and source_data[source_span.start : source_span.end] != staged_data[
            staged_span.start : staged_span.end
        ]:
            abort_pending(f"registro DAT nao alvo mudou em {identity}")

    staged_missiles = {
        span.thing_id: span for span in staged_spans if span.category == "missiles"
    }
    for missile in prepared:
        staged = staged_missiles[missile.missile_id].appearances[0]
        reference = source_missiles[missile.reference_missile_id].appearances[0]
        expected_structure = (
            reference.width,
            reference.height,
            reference.exact_size,
            reference.layers,
            reference.pattern_x,
            reference.pattern_y,
            reference.pattern_z,
            missile.frames,
        )
        staged_structure = (
            staged.width,
            staged.height,
            staged.exact_size,
            staged.layers,
            staged.pattern_x,
            staged.pattern_y,
            staged.pattern_z,
            staged.frames,
        )
        if staged_structure != expected_structure:
            abort_pending(f"estrutura divergente no Missile ID {missile.missile_id}")
        if staged.sprite_ids != missile.sprite_ids:
            abort_pending(f"Sprite IDs DAT divergentes no Missile ID {missile.missile_id}")

    written_blocks = read_spr_blocks(targets["spr"], set(expected_tiles), otfi)
    for sprite_id, expected_tile in expected_tiles.items():
        decoded = decode_sprite_rgba(
            written_blocks[sprite_id], transparency=otfi.transparency
        )
        if decoded != expected_tile:
            abort_pending(f"pixels divergentes apos reabrir Sprite ID {sprite_id}")

    source_hashes_precommit = {
        name: sha256_file(path) for name, path in protected_sources.items()
    }
    if source_hashes_before != source_hashes_precommit:
        abort_pending("um arquivo de origem mudou durante a importacao")
    untouched_before = {
        name: sha256_file(path) for name, path in protected_untouched.items()
    }
    final_report = _commit_transaction(
        root,
        {paths["dat"]: targets["dat"], paths["spr"]: targets["spr"]},
        deep_spr=deep_spr,
    )
    untouched_after = {
        name: sha256_file(path) for name, path in protected_untouched.items()
    }
    if untouched_before != untouched_after:
        raise FormatError("arquivo fora do lote mudou apos o commit")

    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "profile": source_report["profile"]["key"],
        "version_backup": backup,
        "missile_count": len(prepared),
        "new_sprite_count": len(blocks),
        "sprite_id_range": [old_sprite_count + 1, expected_sprite_count],
        "missiles": [asdict(missile) for missile in prepared],
        "transaction_committed": True,
        "output_hashes": {
            "dat": sha256_file(paths["dat"]),
            "spr": sha256_file(paths["spr"]),
        },
        "dat_non_targets_preserved": True,
        "old_sprite_payload_preserved": True,
        "new_sprite_pixels_verified": True,
        "untouched_files_preserved": True,
        "final_validation_passed": final_report["passed"],
        "warnings": final_report["warnings"],
        "errors": [],
        "passed": True,
    }


def import_missiles(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    try:
        return _import_missiles_impl(root, manifest_path, deep_spr=deep_spr)
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
