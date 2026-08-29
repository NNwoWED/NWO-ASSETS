from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
from typing import BinaryIO, Iterable

from .atomic import atomic_binary_output
from .binary import BinaryReader
from .client import FLAG_NAMES_860, _NO_PAYLOAD, _U16_PAYLOAD, inspect_spr
from .errors import FormatError
from .otb import ESCAPE, NODE_END, NODE_START, OtbNode, parse_otb_tree
from .otfi import OtfiConfig


RESERVED_TREE_BYTES = {ESCAPE, NODE_START, NODE_END}


@dataclass(frozen=True)
class DatAppearance:
    width: int
    height: int
    exact_size: int | None
    layers: int
    pattern_x: int
    pattern_y: int
    pattern_z: int
    frames: int
    sprite_ids: tuple[int, ...]


@dataclass(frozen=True)
class DatRecordSpan:
    category: str
    thing_id: int
    start: int
    properties_end: int
    end: int
    appearances: tuple[DatAppearance, ...]


def _require_new_destination(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise FormatError("origem e destino não podem ser o mesmo arquivo")
    if destination.exists():
        raise FormatError(f"destino temporário já existe: {destination}")


def _skip_dat_properties(reader: BinaryReader, category: str, thing_id: int) -> None:
    while True:
        offset = reader.position
        flag = reader.u8()
        if flag == 0xFF:
            return
        if flag not in FLAG_NAMES_860:
            raise FormatError(
                f"{reader.source}: flag 0x{flag:02X} desconhecida em "
                f"{category} {thing_id}, offset {offset}"
            )
        if flag in _NO_PAYLOAD:
            continue
        if flag in _U16_PAYLOAD:
            reader.skip(2)
        elif flag in {0x15, 0x18}:
            reader.skip(4)
        elif flag == 0x21:
            reader.skip(6)
            reader.skip(reader.u16() + 4)
        elif flag == 0x27:
            reader.skip(16)
        else:  # pragma: no cover - protegido pelas tabelas do perfil
            raise FormatError(
                f"{reader.source}: payload não implementado para flag 0x{flag:02X}"
            )


def scan_dat_record_spans(data: bytes, otfi: OtfiConfig, source: str) -> list[DatRecordSpan]:
    reader = BinaryReader(data, source=source)
    reader.u32()
    maxima = {
        "items": reader.u16(),
        "outfits": reader.u16(),
        "effects": reader.u16(),
        "missiles": reader.u16(),
    }
    ranges = (
        ("items", 100, maxima["items"]),
        ("outfits", 1, maxima["outfits"]),
        ("effects", 1, maxima["effects"]),
        ("missiles", 1, maxima["missiles"]),
    )
    spans: list[DatRecordSpan] = []
    for category, first_id, last_id in ranges:
        if last_id < first_id:
            raise FormatError(
                f"{source}: máximo inválido para {category}: {last_id} < {first_id}"
            )
        for thing_id in range(first_id, last_id + 1):
            start = reader.position
            _skip_dat_properties(reader, category, thing_id)
            properties_end = reader.position
            group_count = reader.u8() if otfi.frame_groups and category == "outfits" else 1
            if group_count < 1 or group_count > 2:
                raise FormatError(
                    f"{source}: quantidade de frame groups inválida ({group_count}) "
                    f"em {category} {thing_id}"
                )
            appearances: list[DatAppearance] = []
            for _ in range(group_count):
                if otfi.frame_groups and category == "outfits":
                    reader.u8()
                width = reader.u8()
                height = reader.u8()
                if width == 0 or height == 0:
                    raise FormatError(
                        f"{source}: dimensão {width}x{height} inválida em "
                        f"{category} {thing_id}"
                    )
                exact_size = reader.u8() if width > 1 or height > 1 else None
                dimensions = [width, height]
                dimensions.extend(reader.u8() for _ in range(5))
                if any(value == 0 for value in dimensions):
                    raise FormatError(
                        f"{source}: estrutura visual contém zero em "
                        f"{category} {thing_id}: {tuple(dimensions)}"
                    )
                frames = dimensions[-1]
                total_sprites = 1
                for value in dimensions:
                    total_sprites *= value
                if total_sprites > otfi.sprite_data_size:
                    raise FormatError(
                        f"{source}: {category} {thing_id} referencia "
                        f"{total_sprites} sprites; limite {otfi.sprite_data_size}"
                    )
                if frames > 1 and otfi.frame_durations:
                    reader.skip(1 + 4 + 1 + frames * 8)
                sprite_ids = tuple(
                    reader.u32() if otfi.extended else reader.u16()
                    for _ in range(total_sprites)
                )
                appearances.append(
                    DatAppearance(
                        width=width,
                        height=height,
                        exact_size=exact_size,
                        layers=dimensions[2],
                        pattern_x=dimensions[3],
                        pattern_y=dimensions[4],
                        pattern_z=dimensions[5],
                        frames=frames,
                        sprite_ids=sprite_ids,
                    )
                )
            spans.append(
                DatRecordSpan(
                    category,
                    thing_id,
                    start,
                    properties_end,
                    reader.position,
                    tuple(appearances),
                )
            )
    if reader.position != len(data):
        raise FormatError(
            f"{source}: round-trip DAT terminou no offset {reader.position}, "
            f"mas o arquivo possui {len(data)} bytes"
        )
    return spans


def write_dat_roundtrip(source: Path, destination: Path, otfi: OtfiConfig) -> None:
    _require_new_destination(source, destination)
    data = source.read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(source))
    with atomic_binary_output(destination) as output:
        output.write(data[:12])
        for span in spans:
            output.write(data[span.start : span.end])


def encode_simple_item_appearance(
    width: int,
    height: int,
    sprite_ids: tuple[int, ...],
    otfi: OtfiConfig,
) -> bytes:
    if width < 1 or height < 1 or width > 255 or height > 255:
        raise FormatError(f"dimensões DAT inválidas: {width}x{height}")
    if len(sprite_ids) != width * height:
        raise FormatError(
            f"aparência {width}x{height} exige {width * height} sprites, "
            f"recebeu {len(sprite_ids)}"
        )
    if any(sprite_id <= 0 for sprite_id in sprite_ids):
        raise FormatError("aparência importada não pode referenciar Sprite ID zero")
    output = bytearray((width, height))
    if width > 1 or height > 1:
        exact_size = max(width, height) * otfi.sprite_size
        if exact_size > 0xFF:
            raise FormatError(
                f"exactSize {exact_size} excede o byte do DAT para {width}x{height}"
            )
        output.append(exact_size)
    output.extend((1, 1, 1, 1, 1))
    sprite_format = "<I" if otfi.extended else "<H"
    maximum = 0xFFFFFFFF if otfi.extended else 0xFFFF
    for sprite_id in sprite_ids:
        if sprite_id > maximum:
            raise FormatError(f"Sprite ID {sprite_id} excede o perfil")
        output.extend(struct.pack(sprite_format, sprite_id))
    return bytes(output)


def write_dat_item_appearances(
    source: Path,
    destination: Path,
    otfi: OtfiConfig,
    replacements: dict[int, bytes],
) -> dict[int, DatRecordSpan]:
    _require_new_destination(source, destination)
    data = source.read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(source))
    items = {span.thing_id: span for span in spans if span.category == "items"}
    missing = sorted(set(replacements) - set(items))
    if missing:
        raise FormatError(f"Client IDs DAT inexistentes: {missing}")
    with atomic_binary_output(destination) as output:
        output.write(data[:12])
        for span in spans:
            if span.category == "items" and span.thing_id in replacements:
                output.write(data[span.start : span.properties_end])
                output.write(replacements[span.thing_id])
            else:
                output.write(data[span.start : span.end])
    return {thing_id: items[thing_id] for thing_id in replacements}


def _dat_property_chunks(
    data: bytes, span: DatRecordSpan, source: str
) -> list[tuple[int, bytes]]:
    """Return complete property chunks, excluding the final 0xFF marker."""

    reader = BinaryReader(
        data[span.start : span.properties_end],
        source=f"{source}:{span.category}-{span.thing_id}-properties",
    )
    chunks: list[tuple[int, bytes]] = []
    while True:
        start = reader.position
        flag = reader.u8()
        if flag == 0xFF:
            if reader.remaining:
                raise FormatError(f"{reader.source}: bytes depois do terminador")
            return chunks
        if flag not in FLAG_NAMES_860:
            raise FormatError(f"{reader.source}: flag DAT desconhecida 0x{flag:02X}")
        if flag in _NO_PAYLOAD:
            pass
        elif flag in _U16_PAYLOAD:
            reader.skip(2)
        elif flag in {0x15, 0x18}:
            reader.skip(4)
        elif flag == 0x21:
            reader.skip(6)
            reader.skip(reader.u16() + 4)
        elif flag == 0x27:
            reader.skip(16)
        else:  # pragma: no cover - protegido pelas tabelas do perfil
            raise FormatError(f"{reader.source}: payload não implementado")
        chunks.append((flag, data[span.start + start : span.start + reader.position]))


def dat_item_flags(
    data: bytes, otfi: OtfiConfig, source: str
) -> dict[int, tuple[int, ...]]:
    result: dict[int, tuple[int, ...]] = {}
    for span in scan_dat_record_spans(data, otfi, source):
        if span.category == "items":
            result[span.thing_id] = tuple(
                flag for flag, _ in _dat_property_chunks(data, span, source)
            )
    return result


def write_dat_item_flags(
    source: Path,
    destination: Path,
    otfi: OtfiConfig,
    edits: dict[int, tuple[set[int], set[int]]],
) -> dict[int, dict[str, tuple[int, ...]]]:
    """Edit only boolean DAT flags and preserve all payload properties verbatim."""

    _require_new_destination(source, destination)
    data = source.read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(source))
    items = {span.thing_id: span for span in spans if span.category == "items"}
    missing = sorted(set(edits) - set(items))
    if missing:
        raise FormatError(f"Client IDs DAT inexistentes: {missing}")

    changes: dict[int, dict[str, tuple[int, ...]]] = {}
    replacements: dict[int, bytes] = {}
    for thing_id, (add, remove) in edits.items():
        invalid = sorted((add | remove) - _NO_PAYLOAD)
        if invalid:
            names = [FLAG_NAMES_860.get(value, f"0x{value:02X}") for value in invalid]
            raise FormatError(
                "o editor DAT aceita somente flags sem payload; inválidas: "
                + ", ".join(names)
            )
        conflict = add & remove
        if conflict:
            raise FormatError(
                f"Client ID {thing_id}: flags simultaneamente adicionadas e removidas: "
                f"{sorted(conflict)}"
            )
        chunks = _dat_property_chunks(data, items[thing_id], str(source))
        before = tuple(flag for flag, _ in chunks)
        before_set = set(before)
        after_set = (before_set | add) - remove
        kept = [chunk for flag, chunk in chunks if flag in after_set]
        newly_added = sorted(after_set - before_set)
        encoded = b"".join(kept) + bytes(newly_added) + b"\xFF"
        after = tuple(flag for flag, _ in chunks if flag in after_set) + tuple(newly_added)
        replacements[thing_id] = encoded
        changes[thing_id] = {"before": before, "after": after}

    with atomic_binary_output(destination) as output:
        output.write(data[:12])
        for span in spans:
            if span.category == "items" and span.thing_id in replacements:
                output.write(replacements[span.thing_id])
                output.write(data[span.properties_end : span.end])
            else:
                output.write(data[span.start : span.end])
    return changes


def _validate_sprite_block(block: bytes, otfi: OtfiConfig, label: str) -> None:
    if len(block) < 5 or block[:3] != b"\xFF\x00\xFF":
        raise FormatError(f"{label}: bloco SPR sem color key FF 00 FF")
    payload_length = struct.unpack_from("<H", block, 3)[0]
    if len(block) != 5 + payload_length:
        raise FormatError(
            f"{label}: tamanho do bloco SPR é {len(block)}, "
            f"esperado {5 + payload_length}"
        )
    if payload_length == 0:
        raise FormatError(f"{label}: payload SPR vazio não é permitido")
    payload = memoryview(block)[5:]
    channels = 4 if otfi.transparency else 3
    position = 0
    pixels = 0
    while position < payload_length:
        if position + 4 > payload_length:
            raise FormatError(f"{label}: run SPR truncado")
        transparent, colored = struct.unpack_from("<HH", payload, position)
        position += 4
        colored_bytes = colored * channels
        if position + colored_bytes > payload_length:
            raise FormatError(f"{label}: pixels SPR truncados")
        position += colored_bytes
        pixels += transparent + colored
        if pixels > otfi.sprite_size * otfi.sprite_size:
            raise FormatError(f"{label}: RLE SPR ultrapassa a área física")


def append_spr_blocks(
    source: Path,
    destination: Path,
    otfi: OtfiConfig,
    blocks: Iterable[bytes],
) -> None:
    _require_new_destination(source, destination)
    inspect_spr(source, otfi)
    additions = list(blocks)
    for index, block in enumerate(additions, start=1):
        _validate_sprite_block(block, otfi, f"novo sprite {index}")

    file_size = source.stat().st_size
    count_size = 4 if otfi.extended else 2
    count_format = "<I" if otfi.extended else "<H"
    with source.open("rb") as input_stream:
        signature_raw = input_stream.read(4)
        count_raw = input_stream.read(count_size)
        if len(signature_raw) != 4 or len(count_raw) != count_size:
            raise FormatError(f"{source}: header SPR truncado")
        old_count = struct.unpack(count_format, count_raw)[0]
        new_count = old_count + len(additions)
        limit = 0xFFFFFFFF if otfi.extended else 0xFFFF
        if new_count > limit:
            raise FormatError(f"{source}: count SPR {new_count} excede {limit}")
        offset_bytes = input_stream.read(old_count * 4)
        if len(offset_bytes) != old_count * 4:
            raise FormatError(f"{source}: tabela SPR truncada")
        old_offsets = struct.unpack(f"<{old_count}I", offset_bytes)
        old_table_end = 4 + count_size + old_count * 4
        delta = len(additions) * 4
        shifted = [offset + delta if offset else 0 for offset in old_offsets]
        if any(offset > 0xFFFFFFFF for offset in shifted):
            raise FormatError(f"{source}: offset SPR excede uint32 após expansão")
        next_offset = file_size + delta
        new_offsets: list[int] = []
        for block in additions:
            if next_offset > 0xFFFFFFFF:
                raise FormatError(f"{source}: novo offset SPR excede uint32")
            new_offsets.append(next_offset)
            next_offset += len(block)

        with atomic_binary_output(destination) as output:
            output.write(signature_raw)
            output.write(struct.pack(count_format, new_count))
            if shifted:
                output.write(struct.pack(f"<{len(shifted)}I", *shifted))
            if new_offsets:
                output.write(struct.pack(f"<{len(new_offsets)}I", *new_offsets))
            input_stream.seek(old_table_end)
            shutil.copyfileobj(input_stream, output, length=1024 * 1024)
            for block in additions:
                output.write(block)


def _write_escaped(output: BinaryIO, data: bytes) -> None:
    for value in data:
        if value in RESERVED_TREE_BYTES:
            output.write(bytes((ESCAPE, value)))
        else:
            output.write(bytes((value,)))


def _write_otb_node(output: BinaryIO, node: OtbNode) -> None:
    output.write(bytes((NODE_START,)))
    _write_escaped(output, node.data)
    for child in node.children:
        _write_otb_node(output, child)
    output.write(bytes((NODE_END,)))


def write_otb_roundtrip(source: Path, destination: Path) -> None:
    _require_new_destination(source, destination)
    file_version, root = parse_otb_tree(source)
    write_otb_document(file_version, root, destination)


def write_otb_document(file_version: int, root: OtbNode, destination: Path) -> None:
    with atomic_binary_output(destination) as output:
        output.write(struct.pack("<I", file_version))
        _write_otb_node(output, root)


def write_otbm_roundtrip(source: Path, destination: Path) -> None:
    """Canonical streaming rewrite without materializing millions of map nodes."""

    _require_new_destination(source, destination)
    with source.open("rb", buffering=1024 * 1024) as input_stream:
        identifier = input_stream.read(4)
        if len(identifier) != 4:
            raise FormatError(f"{source}: header OTBM truncado")
        with atomic_binary_output(destination) as output:
            output.write(identifier)
            depth = 0
            roots = 0
            while True:
                raw = input_stream.read(1)
                if not raw:
                    break
                value = raw[0]
                if value == ESCAPE:
                    escaped = input_stream.read(1)
                    if not escaped:
                        raise FormatError(f"{source}: escape truncado no fim do OTBM")
                    _write_escaped(output, escaped)
                elif value == NODE_START:
                    if depth == 0:
                        roots += 1
                    depth += 1
                    output.write(raw)
                elif value == NODE_END:
                    depth -= 1
                    if depth < 0:
                        raise FormatError(f"{source}: fechamento OTBM sem nó aberto")
                    output.write(raw)
                else:
                    if depth == 0:
                        raise FormatError(f"{source}: bytes fora da árvore OTBM")
                    output.write(raw)
            if roots != 1 or depth != 0:
                raise FormatError(
                    f"{source}: árvore OTBM inválida (raízes={roots}, profundidade={depth})"
                )
