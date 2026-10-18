from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import csv
import hashlib
import struct

from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import (
    _commit_transaction,
    _remove_if_exists,
    _sha256_segment,
    _transaction_path,
)
from .otfi import OtfiConfig, parse_otfi
from .pipeline import inspect_client
from .png import PngImage, normalize_rgba, read_png_rgba
from .roundtrip import (
    DatAppearance,
    append_spr_blocks,
    dat_properties_with_added_flags,
    scan_dat_record_spans,
    write_dat_appearances,
)
from .sprites import RGBA_SIZE, decode_sprite_rgba, encode_sprite_rgba, read_spr_blocks
from .versioning import create_version, require_asset_layout


@dataclass(frozen=True)
class OutfitManifestEntry:
    sequence: int
    operation: str
    outfit_id: int
    reference_outfit_id: int
    source_path: Path
    frames: int | None
    frames_per_group: tuple[int, ...] | None
    frame_duration_ms: int | None
    frame_durations_per_group: tuple[int, ...] | None
    dat_add_flags: tuple[int, ...]


@dataclass(frozen=True)
class PreparedOutfit:
    sequence: int
    operation: str
    outfit_id: int
    reference_outfit_id: int
    source_path: str
    file_sha256: str
    pixels_sha256: str
    image_width: int
    image_height: int
    frame_groups: int
    frames_per_group: tuple[int, ...]
    frame_duration_ms: int | None
    frame_durations_per_group: tuple[int, ...] | None
    dat_add_flags: tuple[int, ...]
    sprite_ids: tuple[tuple[int, ...], ...]


OUTFIT_DAT_ADD_FLAGS = {"animate_always": 0x1B}


def read_outfit_manifest(path: Path) -> list[OutfitManifestEntry]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"sequence", "outfit_id", "reference_outfit_id", "source_path"}
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

    entries: list[OutfitManifestEntry] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            sequence = int(row["sequence"])
            outfit_id = int(row["outfit_id"])
            reference_outfit_id = int(row["reference_outfit_id"])
        except (TypeError, ValueError) as exc:
            raise FormatError(f"{path}:{row_number}: valor numerico invalido") from exc
        operation = (row.get("operation") or "reserved").strip().casefold()
        if operation not in {"reserved", "replace"}:
            raise FormatError(
                f"{path}:{row_number}: operation deve ser reserved ou replace"
            )
        raw_frames = (row.get("frames") or "").strip()
        raw_frames_per_group = (row.get("frames_per_group") or "").strip()
        raw_frame_duration = (row.get("frame_duration_ms") or "").strip()
        raw_group_durations = (
            row.get("frame_durations_per_group") or ""
        ).strip()
        raw_dat_add_flags = (row.get("dat_add_flags") or "").strip()
        if raw_frames and raw_frames_per_group:
            raise FormatError(
                f"{path}:{row_number}: use frames ou frames_per_group, nao ambos"
            )
        if raw_frame_duration and raw_group_durations:
            raise FormatError(
                f"{path}:{row_number}: use frame_duration_ms ou "
                "frame_durations_per_group, nao ambos"
            )
        if raw_frames and not raw_frame_duration:
            raise FormatError(
                f"{path}:{row_number}: alteracao de frames exige frame_duration_ms"
            )
        if raw_frames_per_group and not (raw_frame_duration or raw_group_durations):
            raise FormatError(
                f"{path}:{row_number}: alteracao de frame groups exige duracao"
            )
        if raw_group_durations and not raw_frames_per_group:
            raise FormatError(
                f"{path}:{row_number}: frame_durations_per_group exige "
                "frames_per_group"
            )
        frames = None
        frames_per_group = None
        frame_duration_ms = None
        frame_durations_per_group = None
        dat_add_flags: tuple[int, ...] = ()
        if raw_frames:
            try:
                frames = int(raw_frames)
            except ValueError as exc:
                raise FormatError(
                    f"{path}:{row_number}: frames invalido"
                ) from exc
            if not 1 <= frames <= 255:
                raise FormatError(
                    f"{path}:{row_number}: frames fora da faixa"
                )
        if raw_frames_per_group:
            try:
                frames_per_group = tuple(
                    int(value.strip()) for value in raw_frames_per_group.split("|")
                )
            except ValueError as exc:
                raise FormatError(
                    f"{path}:{row_number}: frames_per_group invalido"
                ) from exc
            if not 1 <= len(frames_per_group) <= 2:
                raise FormatError(
                    f"{path}:{row_number}: frames_per_group deve ter 1 ou 2 grupos"
                )
            if any(value < 1 or value > 255 for value in frames_per_group):
                raise FormatError(
                    f"{path}:{row_number}: frames_per_group fora da faixa"
                )
        if raw_frame_duration:
            try:
                frame_duration_ms = int(raw_frame_duration)
            except ValueError as exc:
                raise FormatError(
                    f"{path}:{row_number}: frame_duration_ms invalido"
                ) from exc
            if not 1 <= frame_duration_ms <= 0xFFFFFFFF:
                raise FormatError(
                    f"{path}:{row_number}: frame_duration_ms fora da faixa"
                )
        if raw_group_durations:
            try:
                frame_durations_per_group = tuple(
                    int(value.strip()) for value in raw_group_durations.split("|")
                )
            except ValueError as exc:
                raise FormatError(
                    f"{path}:{row_number}: frame_durations_per_group invalido"
                ) from exc
            if any(
                value < 1 or value > 0xFFFFFFFF
                for value in frame_durations_per_group
            ):
                raise FormatError(
                    f"{path}:{row_number}: frame_durations_per_group fora da faixa"
                )
            if len(frame_durations_per_group) != len(frames_per_group or ()):
                raise FormatError(
                    f"{path}:{row_number}: duracoes por grupo divergem dos grupos"
                )
        if raw_dat_add_flags:
            names = tuple(
                value.strip().casefold()
                for value in raw_dat_add_flags.replace(",", "|").split("|")
                if value.strip()
            )
            unknown = sorted(set(names) - set(OUTFIT_DAT_ADD_FLAGS))
            if unknown:
                raise FormatError(
                    f"{path}:{row_number}: flags DAT de outfit nao suportadas: "
                    + ", ".join(unknown)
                )
            dat_add_flags = tuple(
                sorted({OUTFIT_DAT_ADD_FLAGS[name] for name in names})
            )
        if outfit_id == reference_outfit_id and operation != "replace":
            raise FormatError(
                f"{path}:{row_number}: alvo e referencia iguais exigem operation=replace"
            )
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
            OutfitManifestEntry(
                sequence,
                operation,
                outfit_id,
                reference_outfit_id,
                source,
                frames,
                frames_per_group,
                frame_duration_ms,
                frame_durations_per_group,
                dat_add_flags,
            )
        )

    if [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError(f"{path}: sequence deve ser continua e ordenada")
    target_ids = [entry.outfit_id for entry in entries]
    if len(set(target_ids)) != len(target_ids):
        raise FormatError(f"{path}: Outfit IDs alvo duplicados")
    for entry in entries:
        conflicting_references = {
            other.reference_outfit_id
            for other in entries
            if other.outfit_id != entry.outfit_id
        }
        if entry.outfit_id in conflicting_references:
            raise FormatError(f"{path}: Outfit ID alvo tambem usado como referencia")
    return entries


def _appearance_sheet_size(appearance: DatAppearance, sprite_size: int) -> tuple[int, int]:
    return (
        sprite_size * appearance.width * appearance.layers * appearance.pattern_x,
        sprite_size
        * appearance.height
        * appearance.frames
        * appearance.pattern_y
        * appearance.pattern_z,
    )


def split_outfit_sheet(
    image: PngImage,
    appearances: tuple[DatAppearance, ...],
    sprite_size: int,
) -> tuple[tuple[bytes, ...], ...]:
    """Invert the sheet layout used by compose_appearance_sheet."""

    sizes = [_appearance_sheet_size(appearance, sprite_size) for appearance in appearances]
    expected_widths = {width for width, _height in sizes}
    expected_height = sum(height for _width, height in sizes)
    if len(expected_widths) != 1 or image.width not in expected_widths:
        raise FormatError(
            f"folha possui largura {image.width}; esperado {sorted(expected_widths)}"
        )
    if image.height != expected_height:
        raise FormatError(
            f"folha possui altura {image.height}; esperado {expected_height}"
        )

    image_stride = image.width * 4
    tile_stride = sprite_size * 4
    group_top = 0
    groups: list[tuple[bytes, ...]] = []
    for appearance, (_width, group_height) in zip(appearances, sizes):
        tiles: list[bytes] = []
        for frame in range(appearance.frames):
            for z in range(appearance.pattern_z):
                for y in range(appearance.pattern_y):
                    for x in range(appearance.pattern_x):
                        for layer in range(appearance.layers):
                            for tile_h in range(appearance.height):
                                for tile_w in range(appearance.width):
                                    source_x = sprite_size * (
                                        appearance.width - tile_w - 1
                                        + appearance.width * x
                                        + appearance.width * appearance.pattern_x * layer
                                    )
                                    source_y = group_top + sprite_size * (
                                        appearance.height - tile_h - 1
                                        + appearance.height * y
                                        + appearance.height * appearance.pattern_y * frame
                                        + appearance.height
                                        * appearance.pattern_y
                                        * appearance.frames
                                        * z
                                    )
                                    tile = bytearray(sprite_size * tile_stride)
                                    for row in range(sprite_size):
                                        source = (source_y + row) * image_stride + source_x * 4
                                        target = row * tile_stride
                                        tile[target : target + tile_stride] = image.rgba[
                                            source : source + tile_stride
                                        ]
                                    tiles.append(bytes(tile))
        groups.append(tuple(tiles))
        group_top += group_height
    return tuple(groups)


def replace_outfit_sprite_ids(
    template: bytes,
    appearances: tuple[DatAppearance, ...],
    sprite_ids: tuple[tuple[int, ...], ...],
    otfi: OtfiConfig,
) -> bytes:
    """Keep frame-group metadata byte-for-byte and replace only Sprite IDs."""

    if len(appearances) != len(sprite_ids):
        raise FormatError("quantidade de frame groups diverge da referencia")
    output = bytearray(template)
    position = 0
    group_count = output[position] if otfi.frame_groups else 1
    if otfi.frame_groups:
        position += 1
    if group_count != len(appearances):
        raise FormatError("frame groups do template divergem da referencia")
    sprite_format = "<I" if otfi.extended else "<H"
    sprite_size_bytes = 4 if otfi.extended else 2
    maximum = 0xFFFFFFFF if otfi.extended else 0xFFFF

    for appearance, group_sprite_ids in zip(appearances, sprite_ids):
        if otfi.frame_groups:
            position += 1
        width, height = struct.unpack_from("<BB", output, position)
        position += 2
        if width > 1 or height > 1:
            position += 1
        dimensions = struct.unpack_from("<BBBBB", output, position)
        position += 5
        frames = dimensions[-1]
        expected_count = width * height
        for value in dimensions:
            expected_count *= value
        if frames > 1 and otfi.frame_durations:
            position += 6 + frames * 8
        if (
            width != appearance.width
            or height != appearance.height
            or dimensions
            != (
                appearance.layers,
                appearance.pattern_x,
                appearance.pattern_y,
                appearance.pattern_z,
                appearance.frames,
            )
            or expected_count != len(group_sprite_ids)
        ):
            raise FormatError("estrutura do template diverge da referencia")
        for sprite_id in group_sprite_ids:
            if sprite_id < 0 or sprite_id > maximum:
                raise FormatError(f"Sprite ID {sprite_id} excede o perfil")
            struct.pack_into(sprite_format, output, position, sprite_id)
            position += sprite_size_bytes
    if position != len(output):
        raise FormatError("template de outfit possui bytes residuais")
    return bytes(output)


def replace_outfit_sprite_ids_and_duration(
    template: bytes,
    appearances: tuple[DatAppearance, ...],
    sprite_ids: tuple[tuple[int, ...], ...],
    frame_duration_ms: int,
    otfi: OtfiConfig,
) -> bytes:
    """Replace Sprite IDs and set a fixed duration on every animated group."""

    if not otfi.frame_durations:
        raise FormatError("alteracao de duracao exige frame durations no OTFI")
    output = bytearray(
        replace_outfit_sprite_ids(template, appearances, sprite_ids, otfi)
    )
    position = 0
    group_count = output[position] if otfi.frame_groups else 1
    if otfi.frame_groups:
        position += 1
    if group_count != len(appearances):
        raise FormatError("frame groups do template divergem da referencia")

    sprite_size_bytes = 4 if otfi.extended else 2
    for appearance in appearances:
        if otfi.frame_groups:
            position += 1
        width, height = struct.unpack_from("<BB", output, position)
        position += 2
        if width > 1 or height > 1:
            position += 1
        dimensions = struct.unpack_from("<BBBBB", output, position)
        position += 5
        frames = dimensions[-1]
        if frames > 1:
            position += 6
            for _ in range(frames):
                struct.pack_into(
                    "<II", output, position, frame_duration_ms, frame_duration_ms
                )
                position += 8
        sprite_count = width * height
        for value in dimensions:
            sprite_count *= value
        position += sprite_count * sprite_size_bytes
        if (
            width != appearance.width
            or height != appearance.height
            or dimensions
            != (
                appearance.layers,
                appearance.pattern_x,
                appearance.pattern_y,
                appearance.pattern_z,
                appearance.frames,
            )
        ):
            raise FormatError("estrutura do template diverge da referencia")
    if position != len(output):
        raise FormatError("template de outfit possui bytes residuais")
    return bytes(output)


def replace_outfit_sprite_ids_and_frames(
    template: bytes,
    original: DatAppearance,
    updated: DatAppearance,
    sprite_ids: tuple[int, ...],
    frame_duration_ms: int,
    otfi: OtfiConfig,
) -> bytes:
    """Rebuild one outfit frame group while preserving its visual structure."""

    if not otfi.frame_groups:
        raise FormatError("alteracao de frames de outfit exige frame groups no OTFI")
    if (
        original.width,
        original.height,
        original.exact_size,
        original.layers,
        original.pattern_x,
        original.pattern_y,
        original.pattern_z,
    ) != (
        updated.width,
        updated.height,
        updated.exact_size,
        updated.layers,
        updated.pattern_x,
        updated.pattern_y,
        updated.pattern_z,
    ):
        raise FormatError("alteracao de frames nao pode mudar a estrutura da outfit")

    position = 0
    group_count = template[position]
    position += 1
    if group_count != 1:
        raise FormatError("alteracao de frames suporta somente uma frame group")
    group_type = template[position]
    position += 1
    width, height = struct.unpack_from("<BB", template, position)
    position += 2
    exact_size = None
    if width > 1 or height > 1:
        exact_size = template[position]
        position += 1
    dimensions = struct.unpack_from("<BBBBB", template, position)
    position += 5
    old_frames = dimensions[-1]
    animation_async = False
    loop_count = 0
    start_frame = 0
    if old_frames > 1 and otfi.frame_durations:
        animation_async, loop_count, start_frame = struct.unpack_from(
            "<BiB", template, position
        )
        position += 6 + old_frames * 8
    old_sprite_count = width * height
    for value in dimensions:
        old_sprite_count *= value
    position += old_sprite_count * (4 if otfi.extended else 2)
    if position != len(template):
        raise FormatError("template de outfit possui bytes residuais")
    if (
        width != original.width
        or height != original.height
        or exact_size != original.exact_size
        or dimensions
        != (
            original.layers,
            original.pattern_x,
            original.pattern_y,
            original.pattern_z,
            original.frames,
        )
    ):
        raise FormatError("estrutura do template diverge da outfit original")

    expected_count = (
        updated.width
        * updated.height
        * updated.layers
        * updated.pattern_x
        * updated.pattern_y
        * updated.pattern_z
        * updated.frames
    )
    if len(sprite_ids) != expected_count:
        raise FormatError("quantidade de Sprite IDs diverge da nova estrutura")

    output = bytearray((1, group_type, updated.width, updated.height))
    if updated.width > 1 or updated.height > 1:
        output.append(updated.exact_size or max(updated.width, updated.height) * otfi.sprite_size)
    output.extend(
        (
            updated.layers,
            updated.pattern_x,
            updated.pattern_y,
            updated.pattern_z,
            updated.frames,
        )
    )
    if updated.frames > 1:
        output.extend(
            struct.pack(
                "<BiB",
                int(animation_async),
                loop_count,
                min(start_frame, updated.frames - 1),
            )
        )
        for _ in range(updated.frames):
            output.extend(struct.pack("<II", frame_duration_ms, frame_duration_ms))
    sprite_format = "<I" if otfi.extended else "<H"
    maximum = 0xFFFFFFFF if otfi.extended else 0xFFFF
    for sprite_id in sprite_ids:
        if sprite_id < 0 or sprite_id > maximum:
            raise FormatError(f"Sprite ID {sprite_id} excede o perfil")
        output.extend(struct.pack(sprite_format, sprite_id))
    return bytes(output)


def replace_outfit_sprite_ids_and_frame_groups(
    template: bytes,
    original: tuple[DatAppearance, ...],
    updated: tuple[DatAppearance, ...],
    sprite_ids: tuple[tuple[int, ...], ...],
    frame_durations_ms: tuple[int, ...],
    otfi: OtfiConfig,
) -> bytes:
    """Rebuild idle/walk frame groups while preserving the outfit geometry."""

    if not otfi.frame_groups or not otfi.frame_durations:
        raise FormatError(
            "alteracao de frame groups exige frame groups e durations no OTFI"
        )
    if (
        not 1 <= len(updated) <= 2
        or len(updated) != len(sprite_ids)
        or len(updated) != len(frame_durations_ms)
    ):
        raise FormatError("quantidade de frame groups invalida")
    if len(original) not in {1, len(updated)}:
        raise FormatError("frame groups da referencia incompativeis com a alteracao")

    # Validate the original record before rebuilding it with a different group layout.
    replace_outfit_sprite_ids(
        template,
        original,
        tuple(appearance.sprite_ids for appearance in original),
        otfi,
    )
    for index, appearance in enumerate(updated):
        reference = original[0] if len(original) == 1 else original[index]
        if (
            reference.width,
            reference.height,
            reference.exact_size,
            reference.layers,
            reference.pattern_x,
            reference.pattern_y,
            reference.pattern_z,
        ) != (
            appearance.width,
            appearance.height,
            appearance.exact_size,
            appearance.layers,
            appearance.pattern_x,
            appearance.pattern_y,
            appearance.pattern_z,
        ):
            raise FormatError(
                "alteracao de frame groups nao pode mudar a estrutura da outfit"
            )

    output = bytearray((len(updated),))
    sprite_format = "<I" if otfi.extended else "<H"
    maximum = 0xFFFFFFFF if otfi.extended else 0xFFFF
    for group_type, (appearance, group_sprite_ids, frame_duration_ms) in enumerate(
        zip(updated, sprite_ids, frame_durations_ms)
    ):
        expected_count = (
            appearance.width
            * appearance.height
            * appearance.layers
            * appearance.pattern_x
            * appearance.pattern_y
            * appearance.pattern_z
            * appearance.frames
        )
        if len(group_sprite_ids) != expected_count:
            raise FormatError("quantidade de Sprite IDs diverge da nova estrutura")
        output.extend((group_type, appearance.width, appearance.height))
        if appearance.width > 1 or appearance.height > 1:
            output.append(
                appearance.exact_size
                or min(255, max(appearance.width, appearance.height) * otfi.sprite_size)
            )
        output.extend(
            (
                appearance.layers,
                appearance.pattern_x,
                appearance.pattern_y,
                appearance.pattern_z,
                appearance.frames,
            )
        )
        if appearance.frames > 1:
            output.extend(struct.pack("<BiB", 0, 0, 0))
            for _ in range(appearance.frames):
                output.extend(
                    struct.pack("<II", frame_duration_ms, frame_duration_ms)
                )
        for sprite_id in group_sprite_ids:
            if sprite_id < 0 or sprite_id > maximum:
                raise FormatError(f"Sprite ID {sprite_id} excede o perfil")
            output.extend(struct.pack(sprite_format, sprite_id))
    return bytes(output)


def _import_outfits_impl(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    layout = require_asset_layout(root)
    entries = read_outfit_manifest(manifest_path)
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
    max_outfit_id = int(source_report["dat"]["max_ids"]["outfits"])
    all_ids = [
        value
        for entry in entries
        for value in (entry.outfit_id, entry.reference_outfit_id)
    ]
    invalid_ids = sorted({value for value in all_ids if value < 1 or value > max_outfit_id})
    if invalid_ids:
        raise FormatError(f"Outfit IDs fora da faixa 1..{max_outfit_id}: {invalid_ids}")

    source_data = paths["dat"].read_bytes()
    source_spans = scan_dat_record_spans(source_data, otfi, str(paths["dat"]))
    source_outfits = {
        span.thing_id: span for span in source_spans if span.category == "outfits"
    }
    for entry in entries:
        target = source_outfits[entry.outfit_id]
        reference = source_outfits[entry.reference_outfit_id]
        target_has_sprites = any(
            any(appearance.sprite_ids) for appearance in target.appearances
        )
        if entry.operation == "reserved" and target_has_sprites:
            raise FormatError(f"Outfit ID reservado {entry.outfit_id} nao esta vazio")
        if entry.operation == "replace" and not target_has_sprites:
            raise FormatError(f"Outfit ID para replace {entry.outfit_id} esta vazio")
        if not any(any(appearance.sprite_ids) for appearance in reference.appearances):
            raise FormatError(f"Outfit de referencia {entry.reference_outfit_id} esta vazio")
        if entry.frames is not None:
            if len(reference.appearances) != 1:
                raise FormatError(
                    "alteracao de frames exige referencia com uma frame group"
                )
        if entry.frames_per_group is not None and len(reference.appearances) not in {
            1,
            len(entry.frames_per_group),
        }:
            raise FormatError(
                "alteracao de frame groups exige referencia compativel"
            )

    old_sprite_count = int(source_report["spr"]["sprite_count"])
    next_sprite_id = old_sprite_count + 1
    blank_tile = bytes(RGBA_SIZE)
    blocks: list[bytes] = []
    expected_tiles: dict[int, bytes] = {}
    replacements: dict[int, bytes] = {}
    prepared: list[PreparedOutfit] = []

    for entry in entries:
        reference = source_outfits[entry.reference_outfit_id]
        appearances = reference.appearances
        if entry.frames is not None:
            appearances = (replace(appearances[0], frames=entry.frames),)
        elif entry.frames_per_group is not None:
            appearances = tuple(
                replace(
                    reference.appearances[
                        0 if len(reference.appearances) == 1 else index
                    ],
                    frames=frames,
                )
                for index, frames in enumerate(entry.frames_per_group)
            )
        sizes = [
            _appearance_sheet_size(appearance, otfi.sprite_size)
            for appearance in appearances
        ]
        expected_width = sizes[0][0]
        expected_height = sum(height for _width, height in sizes)
        image = normalize_rgba(
            read_png_rgba(
                entry.source_path,
                max_width=expected_width,
                max_height=expected_height,
            )
        )
        tile_groups = split_outfit_sheet(image, appearances, otfi.sprite_size)
        id_groups: list[tuple[int, ...]] = []
        for tiles in tile_groups:
            group_ids: list[int] = []
            for tile in tiles:
                if tile == blank_tile:
                    group_ids.append(0)
                    continue
                sprite_id = next_sprite_id
                next_sprite_id += 1
                group_ids.append(sprite_id)
                blocks.append(encode_sprite_rgba(tile))
                expected_tiles[sprite_id] = tile
            id_groups.append(tuple(group_ids))
        template = source_data[reference.properties_end : reference.end]
        if entry.frames_per_group is not None:
            group_durations = entry.frame_durations_per_group or (
                (entry.frame_duration_ms,) * len(appearances)
            )
            replacements[entry.outfit_id] = (
                replace_outfit_sprite_ids_and_frame_groups(
                    template,
                    reference.appearances,
                    appearances,
                    tuple(id_groups),
                    group_durations,
                    otfi,
                )
            )
        elif entry.frames is None and entry.frame_duration_ms is None:
            replacements[entry.outfit_id] = replace_outfit_sprite_ids(
                template,
                reference.appearances,
                tuple(id_groups),
                otfi,
            )
        elif entry.frames is None:
            replacements[entry.outfit_id] = replace_outfit_sprite_ids_and_duration(
                template,
                reference.appearances,
                tuple(id_groups),
                entry.frame_duration_ms,
                otfi,
            )
        else:
            replacements[entry.outfit_id] = replace_outfit_sprite_ids_and_frames(
                template,
                reference.appearances[0],
                appearances[0],
                id_groups[0],
                entry.frame_duration_ms,
                otfi,
            )
        prepared.append(
            PreparedOutfit(
                sequence=entry.sequence,
                operation=entry.operation,
                outfit_id=entry.outfit_id,
                reference_outfit_id=entry.reference_outfit_id,
                source_path=str(entry.source_path),
                file_sha256=sha256_file(entry.source_path),
                pixels_sha256=hashlib.sha256(image.rgba).hexdigest().upper(),
                image_width=image.width,
                image_height=image.height,
                frame_groups=len(appearances),
                frames_per_group=tuple(
                    appearance.frames for appearance in appearances
                ),
                frame_duration_ms=entry.frame_duration_ms,
                frame_durations_per_group=entry.frame_durations_per_group,
                dat_add_flags=entry.dat_add_flags,
                sprite_ids=tuple(id_groups),
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
            paths["dat"],
            targets["dat"],
            otfi,
            "outfits",
            replacements,
            {
                outfit.outfit_id: set(outfit.dat_add_flags)
                for outfit in prepared
                if outfit.dat_add_flags
            },
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
    target_keys = {("outfits", outfit_id) for outfit_id in replacements}
    for source_span, staged_span in zip(source_spans, staged_spans):
        identity = (source_span.category, source_span.thing_id)
        if identity != (staged_span.category, staged_span.thing_id):
            abort_pending("ordem de registros DAT mudou durante a importacao")
        additions = next(
            (
                set(outfit.dat_add_flags)
                for outfit in prepared
                if outfit.outfit_id == source_span.thing_id
                and source_span.category == "outfits"
            ),
            set(),
        )
        expected_properties = (
            dat_properties_with_added_flags(
                source_data, source_span, str(paths["dat"]), additions
            )
            if additions
            else source_data[source_span.start : source_span.properties_end]
        )
        if expected_properties != staged_data[
            staged_span.start : staged_span.properties_end
        ]:
            abort_pending(f"propriedades DAT mudaram em {identity}")
        if identity not in target_keys and source_data[source_span.start : source_span.end] != staged_data[
            staged_span.start : staged_span.end
        ]:
            abort_pending(f"registro DAT nao alvo mudou em {identity}")

    staged_outfits = {
        span.thing_id: span for span in staged_spans if span.category == "outfits"
    }
    for outfit in prepared:
        staged_outfit = staged_outfits[outfit.outfit_id]
        staged_appearances = staged_outfit.appearances
        reference_appearances = source_outfits[outfit.reference_outfit_id].appearances
        if len(staged_appearances) != outfit.frame_groups:
            abort_pending(f"frame groups divergentes no Outfit ID {outfit.outfit_id}")
        for index, (staged, expected_frames, expected_ids) in enumerate(
            zip(
                staged_appearances,
                outfit.frames_per_group,
                outfit.sprite_ids,
            )
        ):
            reference = reference_appearances[
                0 if len(reference_appearances) == 1 else index
            ]
            expected = replace(reference, frames=expected_frames)
            if replace(staged, sprite_ids=expected.sprite_ids) != expected:
                abort_pending(f"estrutura divergente no Outfit ID {outfit.outfit_id}")
            if staged.sprite_ids != expected_ids:
                abort_pending(f"Sprite IDs DAT divergentes no Outfit ID {outfit.outfit_id}")
        staged_visual = staged_data[staged_outfit.properties_end : staged_outfit.end]
        if staged_visual != replacements[outfit.outfit_id]:
            abort_pending(f"metadados visuais divergentes no Outfit ID {outfit.outfit_id}")

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
        "outfit_count": len(prepared),
        "new_sprite_count": len(blocks),
        "sprite_id_range": [old_sprite_count + 1, expected_sprite_count],
        "outfits": [asdict(outfit) for outfit in prepared],
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


def import_outfits(
    root: Path,
    manifest_path: Path,
    *,
    deep_spr: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    try:
        return _import_outfits_impl(root, manifest_path, deep_spr=deep_spr)
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
