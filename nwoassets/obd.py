from __future__ import annotations

from dataclasses import dataclass
import lzma
from pathlib import Path
import struct

from .binary import BinaryReader
from .errors import FormatError
from .otb import OtbNode
from .otfi import OtfiConfig
from .properties import OTB_FLAG_VALUES


_OBD_U16 = {0x00, 0x08, 0x09, 0x1A, 0x1D, 0x1E, 0x21, 0x23}
_OBD_U16_PAIR = {0x16, 0x19}
_OBD_NO_PAYLOAD = (
    set(range(0x01, 0x28)) - _OBD_U16 - _OBD_U16_PAIR - {0x22}
) | {0xFC, 0xFD, 0xFE}


@dataclass(frozen=True)
class ObdProperty:
    flag: int
    payload: bytes


def parse_obd_properties(data: bytes, *, source: str = "<OBD>") -> tuple[ObdProperty, ...]:
    reader = BinaryReader(data, source=source)
    properties: list[ObdProperty] = []
    while reader.remaining:
        flag = reader.u8()
        if flag == 0xFF:
            if reader.remaining:
                raise FormatError(f"{source}: bytes após terminador de propriedades")
            return tuple(properties)
        start = reader.position
        if flag in _OBD_NO_PAYLOAD:
            pass
        elif flag in _OBD_U16:
            reader.skip(2)
        elif flag in _OBD_U16_PAIR:
            reader.skip(4)
        elif flag == 0x22:
            reader.skip(6)
            reader.skip(reader.u16() + 4)
        else:
            raise FormatError(f"{source}: flag OBD desconhecida 0x{flag:02X}")
        properties.append(ObdProperty(flag, data[start:reader.position]))
    raise FormatError(f"{source}: propriedades OBD sem terminador 0xFF")


def dat_properties_from_obd(item: ObdItem) -> bytes:
    """Translate only OBD flags with a known Tibia 8.60 DAT equivalent."""

    result = bytearray()
    for property_ in item.parsed_properties:
        flag = property_.flag
        if flag <= 0x0F:
            dat_flag = flag
        elif 0x11 <= flag <= 0x22:
            dat_flag = flag - 1  # OBD inserts NO_MOVE_ANIMATION at 0x10.
        else:
            raise FormatError(
                f"flag OBD 0x{flag:02X} não tem equivalência DAT 8.60 segura"
            )
        result.append(dat_flag)
        result.extend(property_.payload)
    result.append(0xFF)
    return bytes(result)


def encode_obd_appearance(
    item: ObdItem, sprite_ids: tuple[int, ...], otfi: OtfiConfig
) -> bytes:
    if len(sprite_ids) != len(item.argb_tiles):
        raise FormatError(
            f"aparência OBD exige {len(item.argb_tiles)} Sprite IDs, "
            f"recebeu {len(sprite_ids)}"
        )
    if any(sprite_id < 1 or sprite_id > 0xFFFFFFFF for sprite_id in sprite_ids):
        raise FormatError("Sprite IDs de aparência OBD fora do intervalo válido")
    if not otfi.extended:
        raise FormatError("OBD v2 exige Sprite IDs estendidos")
    if item.frames > 1 and not otfi.frame_durations:
        raise FormatError("perfil OTFI não suporta duração de frames")
    output = bytearray((item.width, item.height))
    if item.exact_size is not None:
        output.append(item.exact_size)
    output.extend(
        (
            item.layers,
            item.pattern_x,
            item.pattern_y,
            item.pattern_z,
            item.frames,
        )
    )
    if item.frames > 1:
        if item.animation_mode is None or item.loop_count is None or item.start_frame is None:
            raise FormatError("metadados de animação OBD ausentes")
        output.extend(
            struct.pack(
                "<BiB", item.animation_mode, item.loop_count, item.start_frame
            )
        )
        for minimum, maximum in item.durations:
            output.extend(struct.pack("<II", minimum, maximum))
    for sprite_id in sprite_ids:
        output.extend(struct.pack("<I", sprite_id))
    return bytes(output)


def make_obd_otb_node(
    item: ObdItem, *, server_id: int, client_id: int, sprite_hash: bytes
) -> OtbNode:
    if not 1 <= server_id <= 0xFFFF or not 1 <= client_id <= 0xFFFF:
        raise FormatError("Server ID e Client ID devem caber em uint16")
    if len(sprite_hash) != 16:
        raise FormatError("SpriteHash OTB deve possuir 16 bytes")
    properties = {entry.flag: entry.payload for entry in item.parsed_properties}
    if len(properties) != len(item.parsed_properties):
        raise FormatError("OBD contém propriedade duplicada")
    supported = {
        0x00,  # ground
        0x01,  # ground border
        0x02,  # on bottom
        0x03,  # on top
        0x05,  # stackable
        0x0C,  # unpassable
        0x0D,  # unmoveable
        0x0E,  # block missile
        0x0F,  # block pathfind
        0x11,  # pickupable
        0x12,  # hangable
        0x13,  # vertical
        0x14,  # horizontal
        0x15,  # rotatable
        0x16,  # light
        0x1A,  # elevation
        0x1D,  # minimap
        0x1F,  # full ground (DAT-only)
        0x20,  # ignore look (DAT-only)
    }
    unsupported = sorted(set(properties) - supported)
    if unsupported:
        raise FormatError(
            "OBD possui propriedades sem mapeamento OTB seguro: "
            + ", ".join(f"0x{flag:02X}" for flag in unsupported)
        )
    stack = [flag for flag in (0x01, 0x02, 0x03) if flag in properties]
    if len(stack) > 1:
        raise FormatError("OBD possui múltiplas posições de stack")
    group = 1 if 0x00 in properties else 0
    flags = 0
    direct = {
        0x05: "stackable",
        0x0C: "block_solid",
        0x0E: "block_projectile",
        0x0F: "block_pathfind",
        0x11: "pickupable",
        0x12: "hangable",
        0x13: "vertical",
        0x14: "horizontal",
        0x15: "rotatable",
        0x1A: "has_height",
    }
    for property_flag, otb_name in direct.items():
        if property_flag in properties:
            flags |= OTB_FLAG_VALUES[otb_name]
    if 0x0D not in properties:
        flags |= OTB_FLAG_VALUES["movable"]
    if stack:
        flags |= OTB_FLAG_VALUES["always_on_top"]
    if group == 1 and 0x0C not in properties:
        flags |= OTB_FLAG_VALUES["walk_stack"]
    if item.frames > 1:
        flags |= OTB_FLAG_VALUES["animation"]

    attributes: list[tuple[int, bytes]] = [
        (0x10, struct.pack("<H", server_id)),
        (0x11, struct.pack("<H", client_id)),
        (0x20, sprite_hash),
    ]
    for property_flag, attribute in ((0x00, 0x14), (0x16, 0x2A), (0x1D, 0x21)):
        if property_flag in properties:
            attributes.append((attribute, properties[property_flag]))
    if stack:
        attributes.append((0x2B, bytes((stack[0],))))
    data = bytearray((group,))
    data.extend(struct.pack("<I", flags))
    for attribute, payload in attributes:
        data.append(attribute)
        data.extend(struct.pack("<H", len(payload)))
        data.extend(payload)
    return OtbNode(bytes(data), [])


@dataclass(frozen=True)
class ObdItem:
    client_version: int
    properties: bytes
    parsed_properties: tuple[ObdProperty, ...]
    width: int
    height: int
    exact_size: int | None
    layers: int
    pattern_x: int
    pattern_y: int
    pattern_z: int
    frames: int
    animation_mode: int | None
    loop_count: int | None
    start_frame: int | None
    durations: tuple[tuple[int, int], ...]
    original_sprite_ids: tuple[int, ...]
    argb_tiles: tuple[bytes, ...]

    @property
    def layout(self) -> tuple[int, ...]:
        return (
            self.width,
            self.height,
            self.layers,
            self.pattern_x,
            self.pattern_y,
            self.pattern_z,
            self.frames,
        )

    def rgba_tiles(self) -> tuple[bytes, ...]:
        tiles: list[bytes] = []
        for argb in self.argb_tiles:
            rgba = bytearray(len(argb))
            for offset in range(0, len(argb), 4):
                alpha, red, green, blue = argb[offset : offset + 4]
                rgba[offset : offset + 4] = (
                    bytes((red, green, blue, alpha)) if alpha else b"\0\0\0\0"
                )
            tiles.append(bytes(rgba))
        return tuple(tiles)


def read_obd_item(path: Path) -> ObdItem:
    """Read a Tibia 8.60 Object Builder v2 item without discarding patterns."""

    if path.stat().st_size > 16 * 1024 * 1024:
        raise FormatError(f"{path}: OBD excede 16 MiB comprimidos")
    try:
        data = lzma.decompress(path.read_bytes(), format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as error:
        raise FormatError(f"{path}: LZMA inválido: {error}") from error
    if len(data) > 32 * 1024 * 1024:
        raise FormatError(f"{path}: OBD excede 32 MiB descomprimidos")
    reader = BinaryReader(data, source=str(path))
    version = reader.u16()
    client_version = reader.u16()
    category = reader.u8()
    appearance_offset = reader.u32()
    if (version, client_version, category) != (200, 860, 1):
        raise FormatError(
            f"{path}: esperado OBD v2 de item 8.60; recebido "
            f"version={version}, client={client_version}, category={category}"
        )
    if not reader.position < appearance_offset < len(data):
        raise FormatError(f"{path}: offset da aparência inválido: {appearance_offset}")
    property_start = reader.position
    properties = data[property_start:appearance_offset]
    parsed_properties = parse_obd_properties(properties, source=str(path))
    reader.position = appearance_offset

    width = reader.u8()
    height = reader.u8()
    if not 1 <= width <= 255 or not 1 <= height <= 255:
        raise FormatError(f"{path}: dimensões inválidas {width}x{height}")
    exact_size = reader.u8() if width > 1 or height > 1 else None
    layers = reader.u8()
    pattern_x = reader.u8()
    pattern_y = reader.u8()
    pattern_z = reader.u8()
    frames = reader.u8()
    layout = (width, height, layers, pattern_x, pattern_y, pattern_z, frames)
    if any(dimension < 1 for dimension in layout):
        raise FormatError(f"{path}: estrutura visual inválida: {layout}")
    sprite_count = 1
    for dimension in layout:
        sprite_count *= dimension
    if sprite_count > 4096:
        raise FormatError(f"{path}: {sprite_count} sprites excedem o limite 4096")

    animation_mode = loop_count = start_frame = None
    durations: list[tuple[int, int]] = []
    if frames > 1:
        animation_mode = reader.u8()
        loop_count = reader.i32()
        start_frame = reader.u8()
        if start_frame >= frames:
            raise FormatError(f"{path}: start_frame {start_frame} >= frames {frames}")
        for _ in range(frames):
            minimum, maximum = reader.u32(), reader.u32()
            if minimum < 1 or maximum < minimum:
                raise FormatError(f"{path}: duração de frame inválida {minimum}-{maximum}")
            durations.append((minimum, maximum))

    expected_size = sprite_count * (4 + 4096)
    if reader.remaining != expected_size:
        raise FormatError(
            f"{path}: sprites exigem {expected_size} bytes, "
            f"restam {reader.remaining}"
        )
    original_sprite_ids: list[int] = []
    argb_tiles: list[bytes] = []
    for _ in range(sprite_count):
        original_sprite_ids.append(reader.u32())
        argb_tiles.append(reader.bytes(4096))
    return ObdItem(
        client_version=client_version,
        properties=properties,
        parsed_properties=parsed_properties,
        width=width,
        height=height,
        exact_size=exact_size,
        layers=layers,
        pattern_x=pattern_x,
        pattern_y=pattern_y,
        pattern_z=pattern_z,
        frames=frames,
        animation_mode=animation_mode,
        loop_count=loop_count,
        start_frame=start_frame,
        durations=tuple(durations),
        original_sprite_ids=tuple(original_sprite_ids),
        argb_tiles=tuple(argb_tiles),
    )
