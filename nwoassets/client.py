from __future__ import annotations

from collections import Counter
from pathlib import Path
import os
import struct

from .binary import BinaryReader
from .errors import FormatError
from .otfi import OtfiConfig


FLAG_NAMES_860 = {
    0x00: "ground",
    0x01: "ground_border",
    0x02: "on_bottom",
    0x03: "on_top",
    0x04: "container",
    0x05: "stackable",
    0x06: "force_use",
    0x07: "multi_use",
    0x08: "writable",
    0x09: "writable_once",
    0x0A: "fluid_container",
    0x0B: "fluid",
    0x0C: "unpassable",
    0x0D: "unmoveable",
    0x0E: "block_missile",
    0x0F: "block_pathfind",
    0x10: "pickupable",
    0x11: "hangable",
    0x12: "vertical",
    0x13: "horizontal",
    0x14: "rotatable",
    0x15: "has_light",
    0x16: "dont_hide",
    0x17: "translucent",
    0x18: "has_offset",
    0x19: "has_elevation",
    0x1A: "lying_object",
    0x1B: "animate_always",
    0x1C: "mini_map",
    0x1D: "lens_help",
    0x1E: "full_ground",
    0x1F: "ignore_look",
    0x20: "cloth",
    0x21: "market_item",
    # Extensão observada nesta base customizada. No MetadataReader5 oficial
    # 0x22 não existe; aqui aparece sem payload antes de 0xFF.
    0x22: "custom_flag_22",
    0x27: "has_bones",
}

_NO_PAYLOAD = {
    0x01,
    0x02,
    0x03,
    0x04,
    0x05,
    0x06,
    0x07,
    0x0A,
    0x0B,
    0x0C,
    0x0D,
    0x0E,
    0x0F,
    0x10,
    0x11,
    0x12,
    0x13,
    0x14,
    0x16,
    0x17,
    0x1A,
    0x1B,
    0x1E,
    0x1F,
    0x22,
}
_U16_PAYLOAD = {0x00, 0x08, 0x09, 0x19, 0x1C, 0x1D, 0x20}


def read_dat_header(path: Path) -> dict[str, int | str]:
    with path.open("rb") as stream:
        data = stream.read(12)
    if len(data) != 12:
        raise FormatError(f"{path}: header DAT truncado")
    signature, max_item, max_outfit, max_effect, max_missile = struct.unpack(
        "<IHHHH", data
    )
    return {
        "signature": f"0x{signature:08X}",
        "signature_value": signature,
        "max_item_id": max_item,
        "max_outfit_id": max_outfit,
        "max_effect_id": max_effect,
        "max_missile_id": max_missile,
    }


def _read_properties(
    reader: BinaryReader,
    *,
    category: str,
    thing_id: int,
    flag_counts: Counter[str],
    custom_flag_occurrences: list[dict[str, int | str]],
) -> None:
    while True:
        flag_offset = reader.position
        flag = reader.u8()
        if flag == 0xFF:
            return
        name = FLAG_NAMES_860.get(flag)
        if name is None:
            raise FormatError(
                f"{reader.source}: flag 0x{flag:02X} desconhecida em "
                f"{category} {thing_id}, offset {flag_offset}"
            )
        flag_counts[name] += 1
        if flag == 0x22:
            custom_flag_occurrences.append(
                {
                    "category": category,
                    "thing_id": thing_id,
                    "offset": flag_offset,
                }
            )
        if flag in _NO_PAYLOAD:
            continue
        if flag in _U16_PAYLOAD:
            reader.skip(2)
        elif flag in {0x15, 0x18}:
            reader.skip(4)
        elif flag == 0x21:
            reader.skip(6)
            name_length = reader.u16()
            reader.skip(name_length + 4)
        elif flag == 0x27:
            reader.skip(16)
        else:  # pragma: no cover - protegido pela tabela acima
            raise FormatError(
                f"{reader.source}: payload não implementado para flag 0x{flag:02X}"
            )


def inspect_dat(
    path: Path,
    otfi: OtfiConfig,
    *,
    expected_metadata_reader: int,
    sprite_count: int | None = None,
) -> dict[str, object]:
    if expected_metadata_reader != 5:
        raise FormatError(
            "esta versão da CLI só faz parse semântico completo do MetadataReader5"
        )
    data = path.read_bytes()
    reader = BinaryReader(data, source=str(path))
    signature = reader.u32()
    maxima = {
        "items": reader.u16(),
        "outfits": reader.u16(),
        "effects": reader.u16(),
        "missiles": reader.u16(),
    }
    category_ranges = (
        ("items", 100, maxima["items"]),
        ("outfits", 1, maxima["outfits"]),
        ("effects", 1, maxima["effects"]),
        ("missiles", 1, maxima["missiles"]),
    )

    flag_counts: Counter[str] = Counter()
    custom_flag_occurrences: list[dict[str, int | str]] = []
    record_counts: Counter[str] = Counter()
    referenced_sprites: set[int] = set()
    sprite_reference_count = 0
    zero_sprite_references = 0
    multi_tile_records = 0
    animated_records = 0
    max_sprites_in_group = 0
    item_section_end = 12

    for category, first_id, last_id in category_ranges:
        if last_id < first_id:
            raise FormatError(
                f"{path}: máximo inválido para {category}: {last_id} < {first_id}"
            )
        for thing_id in range(first_id, last_id + 1):
            _read_properties(
                reader,
                category=category,
                thing_id=thing_id,
                flag_counts=flag_counts,
                custom_flag_occurrences=custom_flag_occurrences,
            )
            group_count = reader.u8() if otfi.frame_groups and category == "outfits" else 1
            if group_count < 1 or group_count > 2:
                raise FormatError(
                    f"{path}: quantidade de frame groups inválida ({group_count}) "
                    f"em {category} {thing_id}, offset {reader.position - 1}"
                )
            for _ in range(group_count):
                if otfi.frame_groups and category == "outfits":
                    reader.u8()  # frame group type
                width = reader.u8()
                height = reader.u8()
                if width == 0 or height == 0:
                    raise FormatError(
                        f"{path}: dimensão {width}x{height} inválida em "
                        f"{category} {thing_id}"
                    )
                if width > 1 or height > 1:
                    reader.u8()  # exact size
                    multi_tile_records += 1
                layers = reader.u8()
                pattern_x = reader.u8()
                pattern_y = reader.u8()
                pattern_z = reader.u8()
                frames = reader.u8()
                dimensions = (
                    width,
                    height,
                    layers,
                    pattern_x,
                    pattern_y,
                    pattern_z,
                    frames,
                )
                if any(value == 0 for value in dimensions):
                    raise FormatError(
                        f"{path}: estrutura visual contém zero em "
                        f"{category} {thing_id}: {dimensions}"
                    )
                total_sprites = 1
                for value in dimensions:
                    total_sprites *= value
                if total_sprites > otfi.sprite_data_size:
                    raise FormatError(
                        f"{path}: {category} {thing_id} referencia "
                        f"{total_sprites} sprites; limite {otfi.sprite_data_size}"
                    )
                max_sprites_in_group = max(max_sprites_in_group, total_sprites)
                if frames > 1:
                    animated_records += 1
                    if otfi.frame_durations:
                        reader.skip(1 + 4 + 1 + frames * 8)
                for _ in range(total_sprites):
                    sprite_id = reader.u32() if otfi.extended else reader.u16()
                    sprite_reference_count += 1
                    if sprite_id == 0:
                        zero_sprite_references += 1
                    else:
                        referenced_sprites.add(sprite_id)
                        if sprite_count is not None and sprite_id > sprite_count:
                            raise FormatError(
                                f"{path}: {category} {thing_id} referencia Sprite ID "
                                f"{sprite_id}, acima do count SPR {sprite_count}"
                            )
            record_counts[category] += 1
        if category == "items":
            item_section_end = reader.position

    if reader.position != len(data):
        raise FormatError(
            f"{path}: parse terminou no offset {reader.position}, "
            f"mas o arquivo possui {len(data)} bytes"
        )

    return {
        "path": str(path),
        "size": len(data),
        "signature": f"0x{signature:08X}",
        "max_ids": maxima,
        "record_counts": dict(record_counts),
        "total_records": sum(record_counts.values()),
        "items_end_offset": item_section_end,
        "parsed_end_offset": reader.position,
        "flag_counts": dict(sorted(flag_counts.items())),
        "custom_flag_22_occurrences": custom_flag_occurrences,
        "appearance": {
            "multi_tile_groups": multi_tile_records,
            "animated_groups": animated_records,
            "max_sprites_in_group": max_sprites_in_group,
            "sprite_reference_count": sprite_reference_count,
            "unique_nonzero_sprite_ids": len(referenced_sprites),
            "zero_sprite_references": zero_sprite_references,
            "min_referenced_sprite_id": min(referenced_sprites, default=None),
            "max_referenced_sprite_id": max(referenced_sprites, default=None),
        },
    }


def inspect_spr(
    path: Path,
    otfi: OtfiConfig,
    *,
    deep: bool = False,
) -> dict[str, object]:
    file_size = os.path.getsize(path)
    with path.open("rb", buffering=1024 * 1024) as stream:
        signature_data = stream.read(4)
        if len(signature_data) != 4:
            raise FormatError(f"{path}: assinatura SPR truncada")
        signature = struct.unpack("<I", signature_data)[0]
        count_size = 4 if otfi.extended else 2
        count_data = stream.read(count_size)
        if len(count_data) != count_size:
            raise FormatError(f"{path}: contagem SPR truncada")
        sprite_count = struct.unpack("<I" if otfi.extended else "<H", count_data)[0]
        table_start = 4 + count_size
        table_end = table_start + sprite_count * 4
        if table_end > file_size:
            raise FormatError(
                f"{path}: tabela SPR termina em {table_end}, além do arquivo {file_size}"
            )
        offset_bytes = stream.read(sprite_count * 4)
        if len(offset_bytes) != sprite_count * 4:
            raise FormatError(f"{path}: tabela de offsets SPR truncada")
        offsets = struct.unpack(f"<{sprite_count}I", offset_bytes)

        zero_offsets = 0
        invalid_offsets: list[dict[str, int]] = []
        nonzero_offsets: list[tuple[int, int]] = []
        for sprite_id, offset in enumerate(offsets, start=1):
            if offset == 0:
                zero_offsets += 1
            elif offset < table_end or offset + 5 > file_size:
                if len(invalid_offsets) < 20:
                    invalid_offsets.append({"sprite_id": sprite_id, "offset": offset})
            else:
                nonzero_offsets.append((sprite_id, offset))
        if invalid_offsets:
            raise FormatError(
                f"{path}: offsets SPR inválidos: {invalid_offsets[:5]}"
            )

        deep_stats: dict[str, object] = {"enabled": deep}
        if deep:
            color_key_mismatches = 0
            truncated_blocks = 0
            rle_overflows = 0
            payload_zero = 0
            explicit_transparent = 0
            channels = 4 if otfi.transparency else 3
            for _sprite_id, offset in sorted(nonzero_offsets, key=lambda pair: pair[1]):
                stream.seek(offset)
                header = stream.read(5)
                if len(header) != 5:
                    truncated_blocks += 1
                    continue
                if header[:3] != b"\xFF\x00\xFF":
                    color_key_mismatches += 1
                payload_length = struct.unpack("<H", header[3:])[0]
                if payload_length == 0:
                    payload_zero += 1
                if offset + 5 + payload_length > file_size:
                    truncated_blocks += 1
                    continue
                payload = stream.read(payload_length)
                if len(payload) != payload_length:
                    truncated_blocks += 1
                    continue
                position = 0
                pixels = 0
                colored_total = 0
                valid = True
                while position < payload_length:
                    if position + 4 > payload_length:
                        valid = False
                        break
                    transparent, colored = struct.unpack_from("<HH", payload, position)
                    position += 4
                    colored_bytes = colored * channels
                    if position + colored_bytes > payload_length:
                        valid = False
                        break
                    position += colored_bytes
                    pixels += transparent + colored
                    colored_total += colored
                    if pixels > otfi.sprite_size * otfi.sprite_size:
                        valid = False
                        break
                if not valid or position != payload_length:
                    rle_overflows += 1
                elif colored_total == 0 and payload_length > 0:
                    explicit_transparent += 1
            deep_stats.update(
                {
                    "color_key_mismatches": color_key_mismatches,
                    "truncated_blocks": truncated_blocks,
                    "rle_invalid_blocks": rle_overflows,
                    "payload_zero_blocks": payload_zero,
                    "explicit_transparent_blocks": explicit_transparent,
                    "passed": not (
                        color_key_mismatches or truncated_blocks or rle_overflows
                    ),
                }
            )

    unique_nonzero = len({offset for _, offset in nonzero_offsets})
    return {
        "path": str(path),
        "size": file_size,
        "signature": f"0x{signature:08X}",
        "signature_value": signature,
        "sprite_count": sprite_count,
        "table_start": table_start,
        "table_end": table_end,
        "zero_offsets": zero_offsets,
        "nonzero_offsets": len(nonzero_offsets),
        "unique_nonzero_offsets": unique_nonzero,
        "shared_offsets": len(nonzero_offsets) - unique_nonzero,
        "min_nonzero_offset": min((offset for _, offset in nonzero_offsets), default=None),
        "max_nonzero_offset": max((offset for _, offset in nonzero_offsets), default=None),
        "deep_validation": deep_stats,
    }
