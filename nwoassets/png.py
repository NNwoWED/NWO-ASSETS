from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import binascii
import struct
import zlib

from .errors import FormatError


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_ITEM_DIMENSION = 224


@dataclass(frozen=True)
class PngImage:
    width: int
    height: int
    rgba: bytes


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distance_left = abs(estimate - left)
    distance_above = abs(estimate - above)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def read_png_rgba(path: Path) -> PngImage:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise FormatError(f"{path}: assinatura PNG inválida")

    position = len(PNG_SIGNATURE)
    width = height = 0
    idat = bytearray()
    saw_ihdr = False
    saw_iend = False
    while position < len(data):
        if position + 12 > len(data):
            raise FormatError(f"{path}: chunk PNG truncado")
        length = struct.unpack_from(">I", data, position)[0]
        chunk_type = data[position + 4 : position + 8]
        chunk_end = position + 12 + length
        if chunk_end > len(data):
            raise FormatError(f"{path}: payload PNG truncado em {chunk_type!r}")
        payload = data[position + 8 : position + 8 + length]
        expected_crc = struct.unpack_from(">I", data, position + 8 + length)[0]
        actual_crc = binascii.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise FormatError(f"{path}: CRC inválido no chunk {chunk_type!r}")

        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13:
                raise FormatError(f"{path}: IHDR inválido")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if width == 0 or height == 0:
                raise FormatError(f"{path}: dimensões PNG inválidas {width}x{height}")
            if width > MAX_ITEM_DIMENSION or height > MAX_ITEM_DIMENSION:
                raise FormatError(
                    f"{path}: dimensões {width}x{height} excedem o limite "
                    f"seguro desta fase ({MAX_ITEM_DIMENSION}x{MAX_ITEM_DIMENSION})"
                )
            if bit_depth != 8 or color_type != 6:
                raise FormatError(
                    f"{path}: use PNG RGBA 8-bit; recebido bit depth {bit_depth}, "
                    f"color type {color_type}"
                )
            if compression != 0 or filtering != 0 or interlace != 0:
                raise FormatError(f"{path}: método PNG ou entrelaçamento não suportado")
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if not saw_ihdr:
                raise FormatError(f"{path}: IDAT antes de IHDR")
            idat.extend(payload)
        elif chunk_type == b"IEND":
            saw_iend = True
            position = chunk_end
            break
        elif chunk_type == b"PLTE":
            pass
        elif chunk_type and 65 <= chunk_type[0] <= 90:
            raise FormatError(f"{path}: chunk crítico PNG não suportado: {chunk_type!r}")
        position = chunk_end

    if not saw_ihdr or not saw_iend or not idat:
        raise FormatError(f"{path}: PNG sem IHDR, IDAT ou IEND")
    if position != len(data):
        raise FormatError(f"{path}: bytes após IEND não são permitidos")

    stride = width * 4
    expected_size = height * (stride + 1)
    try:
        decompressor = zlib.decompressobj()
        filtered = decompressor.decompress(bytes(idat), expected_size + 1)
    except zlib.error as exc:
        raise FormatError(f"{path}: IDAT inválido: {exc}") from exc
    if (
        len(filtered) != expected_size
        or decompressor.unconsumed_tail
        or decompressor.unused_data
        or not decompressor.eof
    ):
        raise FormatError(
            f"{path}: pixels PNG possuem {len(filtered)} bytes, esperado {expected_size}"
        )

    result = bytearray(height * stride)
    previous = bytearray(stride)
    source_position = 0
    for row_index in range(height):
        filter_type = filtered[source_position]
        source_position += 1
        raw = filtered[source_position : source_position + stride]
        source_position += stride
        row = bytearray(stride)
        for index, value in enumerate(raw):
            left = row[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 0:
                decoded = value
            elif filter_type == 1:
                decoded = value + left
            elif filter_type == 2:
                decoded = value + above
            elif filter_type == 3:
                decoded = value + ((left + above) // 2)
            elif filter_type == 4:
                decoded = value + _paeth(left, above, upper_left)
            else:
                raise FormatError(f"{path}: filtro PNG desconhecido {filter_type}")
            row[index] = decoded & 0xFF
        start = row_index * stride
        result[start : start + stride] = row
        previous = row
    return PngImage(width, height, bytes(result))


def normalize_rgba(image: PngImage) -> PngImage:
    pixels = bytearray(image.rgba)
    for position in range(0, len(pixels), 4):
        red, green, blue, alpha = pixels[position : position + 4]
        if alpha == 0 or (red, green, blue, alpha) == (255, 0, 255, 255):
            pixels[position : position + 4] = b"\0\0\0\0"
    return PngImage(image.width, image.height, bytes(pixels))


def split_tiles_bottom_right_first(image: PngImage, sprite_size: int = 32) -> list[bytes]:
    if image.width % sprite_size or image.height % sprite_size:
        raise FormatError(
            f"imagem {image.width}x{image.height} não é múltipla de {sprite_size}"
        )
    width_tiles = image.width // sprite_size
    height_tiles = image.height // sprite_size
    if width_tiles > 255 or height_tiles > 255:
        raise FormatError("dimensões em tiles excedem o uint8 do DAT")
    if width_tiles * height_tiles > 4096:
        raise FormatError("imagem excede o limite de 4096 sprites por aparência")

    tiles: list[bytes] = []
    image_stride = image.width * 4
    tile_stride = sprite_size * 4
    for tile_y in range(height_tiles):
        for tile_x in range(width_tiles):
            left = (width_tiles - tile_x - 1) * sprite_size
            top = (height_tiles - tile_y - 1) * sprite_size
            tile = bytearray(sprite_size * tile_stride)
            for row in range(sprite_size):
                source = (top + row) * image_stride + left * 4
                target = row * tile_stride
                tile[target : target + tile_stride] = image.rgba[source : source + tile_stride]
            tiles.append(bytes(tile))
    return tiles
