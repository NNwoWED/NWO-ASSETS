from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from .errors import FormatError
from .otfi import OtfiConfig


SPRITE_PIXELS = 32 * 32
RGBA_SIZE = SPRITE_PIXELS * 4
TRANSPARENT_BLOCK = b"\xFF\x00\xFF\x04\x00\x00\x04\x00\x00"


def encode_sprite_rgba(rgba: bytes) -> bytes:
    if len(rgba) != RGBA_SIZE:
        raise FormatError(f"tile RGBA possui {len(rgba)} bytes, esperado {RGBA_SIZE}")
    payload = bytearray()
    pixel = 0
    while pixel < SPRITE_PIXELS:
        transparent = 0
        while pixel < SPRITE_PIXELS and rgba[pixel * 4 + 3] == 0:
            transparent += 1
            pixel += 1
        colored_start = pixel
        while pixel < SPRITE_PIXELS and rgba[pixel * 4 + 3] != 0:
            pixel += 1
        colored = pixel - colored_start
        payload.extend(struct.pack("<HH", transparent, colored))
        if colored:
            start = colored_start * 4
            payload.extend(rgba[start : start + colored * 4])
    if not payload:
        return TRANSPARENT_BLOCK
    if len(payload) > 0xFFFF:
        raise FormatError("payload RLE do sprite excede uint16")
    return b"\xFF\x00\xFF" + struct.pack("<H", len(payload)) + payload


def _decode_sprite_rgba(
    block: bytes,
    *,
    transparency: bool,
    preserve_colored_zero_alpha: bool,
) -> bytes:
    if len(block) < 5 or block[:3] != b"\xFF\x00\xFF":
        raise FormatError("bloco SPR inválido")
    payload_length = struct.unpack_from("<H", block, 3)[0]
    if len(block) != payload_length + 5 or payload_length == 0:
        raise FormatError("tamanho ou payload SPR inválido")
    channels = 4 if transparency else 3
    rgba = bytearray(RGBA_SIZE)
    payload = memoryview(block)[5:]
    position = 0
    pixel = 0
    while position < payload_length:
        if position + 4 > payload_length:
            raise FormatError("run SPR truncado")
        transparent, colored = struct.unpack_from("<HH", payload, position)
        position += 4
        pixel += transparent
        if pixel + colored > SPRITE_PIXELS:
            raise FormatError("run SPR ultrapassa 1024 pixels")
        byte_count = colored * channels
        if position + byte_count > payload_length:
            raise FormatError("pixels SPR truncados")
        for _ in range(colored):
            target = pixel * 4
            rgba[target : target + 3] = payload[position : position + 3]
            alpha = payload[position + 3] if transparency else 255
            rgba[target + 3] = (
                1 if preserve_colored_zero_alpha and alpha == 0 else alpha
            )
            position += channels
            pixel += 1
    return bytes(rgba)


def decode_sprite_rgba(block: bytes, *, transparency: bool = True) -> bytes:
    return _decode_sprite_rgba(
        block,
        transparency=transparency,
        preserve_colored_zero_alpha=False,
    )


def decode_sprite_for_hash(block: bytes, *, transparency: bool = True) -> bytes:
    return _decode_sprite_rgba(
        block,
        transparency=transparency,
        preserve_colored_zero_alpha=True,
    )


def read_spr_blocks(
    path: Path,
    sprite_ids: set[int],
    otfi: OtfiConfig,
) -> dict[int, bytes]:
    if not sprite_ids:
        return {}
    count_size = 4 if otfi.extended else 2
    count_format = "<I" if otfi.extended else "<H"
    with path.open("rb", buffering=1024 * 1024) as stream:
        if len(stream.read(4)) != 4:
            raise FormatError(f"{path}: assinatura SPR truncada")
        count_raw = stream.read(count_size)
        if len(count_raw) != count_size:
            raise FormatError(f"{path}: count SPR truncado")
        count = struct.unpack(count_format, count_raw)[0]
        invalid = sorted(sprite_id for sprite_id in sprite_ids if sprite_id < 1 or sprite_id > count)
        if invalid:
            raise FormatError(f"{path}: Sprite IDs fora do count: {invalid[:20]}")
        offsets: dict[int, int] = {}
        for sprite_id in sorted(sprite_ids):
            stream.seek(4 + count_size + (sprite_id - 1) * 4)
            offset_raw = stream.read(4)
            if len(offset_raw) != 4:
                raise FormatError(f"{path}: offset do Sprite ID {sprite_id} truncado")
            offset = struct.unpack("<I", offset_raw)[0]
            if offset == 0:
                raise FormatError(f"{path}: Sprite ID {sprite_id} possui offset zero")
            offsets[sprite_id] = offset
        blocks: dict[int, bytes] = {}
        for sprite_id, offset in offsets.items():
            stream.seek(offset)
            header = stream.read(5)
            if len(header) != 5:
                raise FormatError(f"{path}: bloco do Sprite ID {sprite_id} truncado")
            length = struct.unpack_from("<H", header, 3)[0]
            payload = stream.read(length)
            if len(payload) != length:
                raise FormatError(f"{path}: payload do Sprite ID {sprite_id} truncado")
            blocks[sprite_id] = header + payload
    return blocks


def sprite_hash(tiles: list[bytes]) -> bytes:
    digest = hashlib.md5()
    for rgba in tiles:
        if len(rgba) != RGBA_SIZE:
            raise FormatError("tile inválido durante cálculo de SpriteHash")
        item_editor_bytes = bytearray(RGBA_SIZE)
        for y in range(32):
            source_y = 31 - y
            for x in range(32):
                source = (source_y * 32 + x) * 4
                target = (y * 32 + x) * 4
                red, green, blue, alpha = rgba[source : source + 4]
                if alpha == 0:
                    red = green = blue = 0x11
                item_editor_bytes[target : target + 4] = bytes((blue, green, red, 0))
        digest.update(item_editor_bytes)
    return digest.digest()
