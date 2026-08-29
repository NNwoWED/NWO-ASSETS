from __future__ import annotations

from pathlib import Path
import struct
from typing import BinaryIO

from .errors import FormatError
from .otb import ESCAPE, NODE_END, NODE_START
from .properties import flag_names, read_otb_items
from .properties import dat_flag_names
from .roundtrip import dat_item_flags
from .otfi import parse_otfi
from .versioning import require_asset_layout


# The on-disk root node is 0; the server's FileLoader exposes it as ROOTV2=1.
OTBM_ROOTV2 = 0
OTBM_MAP_DATA = 2
OTBM_TILE_AREA = 4
OTBM_TILE = 5
OTBM_ITEM = 6
OTBM_HOUSETILE = 14
ATTR_TILE_FLAGS = 3
ATTR_ACTION_ID = 4
ATTR_UNIQUE_ID = 5
ATTR_ITEM = 9
ATTR_COUNT = 15


class _TileFound(Exception):
    pass


def _node_data(stream: BinaryIO, source: str) -> tuple[bytes, int]:
    data = bytearray()
    while True:
        raw = stream.read(1)
        if not raw:
            raise FormatError(f"{source}: nó OTBM truncado")
        value = raw[0]
        if value == ESCAPE:
            escaped = stream.read(1)
            if not escaped:
                raise FormatError(f"{source}: escape OTBM truncado")
            data.append(escaped[0])
        elif value in {NODE_START, NODE_END}:
            return bytes(data), value
        else:
            data.append(value)


def _next_marker(stream: BinaryIO, source: str) -> int:
    raw = stream.read(1)
    if not raw:
        raise FormatError(f"{source}: fim inesperado na árvore OTBM")
    if raw[0] not in {NODE_START, NODE_END}:
        raise FormatError(f"{source}: marcador estrutural OTBM inválido 0x{raw[0]:02X}")
    return raw[0]


def _skip_node_remainder(stream: BinaryIO, source: str) -> None:
    """Skip a node after its first child NODE_START was already consumed."""
    depth = 2
    while depth:
        raw = stream.read(1)
        if not raw:
            raise FormatError(f"{source}: subárvore OTBM truncada")
        value = raw[0]
        if value == ESCAPE:
            if not stream.read(1):
                raise FormatError(f"{source}: escape OTBM truncado")
        elif value == NODE_START:
            depth += 1
        elif value == NODE_END:
            depth -= 1


def _decode_item_attributes(raw: bytes) -> dict[str, object]:
    position = 0
    decoded: dict[str, object] = {}
    while position < len(raw):
        attribute = raw[position]
        position += 1
        if attribute == 0:
            break
        if attribute in {ATTR_ACTION_ID, ATTR_UNIQUE_ID}:
            if position + 2 > len(raw):
                position -= 1
                break
            key = "action_id" if attribute == ATTR_ACTION_ID else "unique_id"
            decoded[key] = struct.unpack_from("<H", raw, position)[0]
            position += 2
        elif attribute == ATTR_COUNT:
            if position >= len(raw):
                position -= 1
                break
            decoded["count"] = raw[position]
            position += 1
        else:
            position -= 1
            break
    if position < len(raw):
        decoded["raw_attributes_hex"] = raw[position:].hex().upper()
    return decoded


def _item_report(server_id: int, raw_attributes: bytes, nested_depth: int) -> dict[str, object]:
    return {
        "server_id": server_id,
        "nested_depth": nested_depth,
        **_decode_item_attributes(raw_attributes),
    }


def _parse_tile_data(data: bytes, source: str) -> tuple[int | None, int, list[dict[str, object]]]:
    node_type = data[0]
    position = 7 if node_type == OTBM_HOUSETILE else 3
    house_id = struct.unpack_from("<I", data, 3)[0] if node_type == OTBM_HOUSETILE else None
    tile_flags = 0
    inline: list[dict[str, object]] = []
    while position < len(data):
        attribute = data[position]
        position += 1
        if attribute == ATTR_TILE_FLAGS:
            if position + 4 > len(data):
                raise FormatError(f"{source}: flags do tile truncadas")
            tile_flags = struct.unpack_from("<I", data, position)[0]
            position += 4
        elif attribute == ATTR_ITEM:
            if position + 2 > len(data):
                raise FormatError(f"{source}: item inline truncado")
            inline.append(_item_report(struct.unpack_from("<H", data, position)[0], b"", 0))
            position += 2
        else:
            raise FormatError(f"{source}: atributo de tile desconhecido {attribute}")
    return house_id, tile_flags, inline


def _walk_item(stream: BinaryIO, source: str, result: dict[str, object], depth: int) -> None:
    data, marker = _node_data(stream, source)
    if len(data) < 3 or data[0] != OTBM_ITEM:
        if marker == NODE_START:
            _skip_node_remainder(stream, source)
        return
    server_id = struct.unpack_from("<H", data, 1)[0]
    result["items"].append(_item_report(server_id, data[3:], depth))
    while marker == NODE_START:
        _walk_item(stream, source, result, depth + 1)
        marker = _next_marker(stream, source)
    if marker != NODE_END:
        raise FormatError(f"{source}: item OTBM sem fechamento")


def _walk_node(
    stream: BinaryIO,
    source: str,
    target: tuple[int, int, int],
    result: dict[str, object],
    area: tuple[int, int, int] | None = None,
) -> None:
    data, marker = _node_data(stream, source)
    if not data:
        raise FormatError(f"{source}: nó OTBM sem tipo")
    node_type = data[0]
    next_area = area
    inspect_children = node_type in {OTBM_ROOTV2, OTBM_MAP_DATA}
    if node_type == OTBM_TILE_AREA:
        result["tile_areas_examined"] += 1
        if len(data) < 6:
            raise FormatError(f"{source}: tile area truncada")
        next_area = (*struct.unpack_from("<HH", data, 1), data[5])
        ax, ay, az = next_area
        x, y, z = target
        inspect_children = az == z and ax <= x <= ax + 255 and ay <= y <= ay + 255
        if inspect_children:
            result["matching_tile_areas"] += 1
    elif node_type in {OTBM_TILE, OTBM_HOUSETILE}:
        result["tiles_examined"] += 1
        if area is None or len(data) < (7 if node_type == OTBM_HOUSETILE else 3):
            raise FormatError(f"{source}: tile sem área ou truncado")
        coordinate = (area[0] + data[1], area[1] + data[2], area[2])
        if coordinate != target:
            inspect_children = False
        else:
            house_id, tile_flags, inline = _parse_tile_data(data, source)
            result.update({
                "found": True,
                "node_type": "house_tile" if node_type == OTBM_HOUSETILE else "tile",
                "house_id": house_id,
                "tile_flags": f"0x{tile_flags:08X}",
                "items": inline,
            })
            inspect_children = True
    elif node_type not in {OTBM_ROOTV2, OTBM_MAP_DATA}:
        inspect_children = False

    if not inspect_children:
        if marker == NODE_START:
            _skip_node_remainder(stream, source)
        return
    while marker == NODE_START:
        if node_type in {OTBM_TILE, OTBM_HOUSETILE}:
            _walk_item(stream, source, result, 0)
        else:
            _walk_node(stream, source, target, result, next_area)
        marker = _next_marker(stream, source)
    if marker != NODE_END:
        raise FormatError(f"{source}: nó OTBM sem fechamento")
    if node_type in {OTBM_TILE, OTBM_HOUSETILE} and result["found"]:
        raise _TileFound


def inspect_position_file(path: Path, x: int, y: int, z: int) -> dict[str, object]:
    if not (0 <= x <= 0xFFFF and 0 <= y <= 0xFFFF and 0 <= z <= 0xFF):
        raise FormatError("posição fora dos limites uint16/uint16/uint8")
    result: dict[str, object] = {
        "map": str(path), "position": {"x": x, "y": y, "z": z},
        "found": False, "items": [], "tile_areas_examined": 0,
        "matching_tile_areas": 0, "tiles_examined": 0,
    }
    with path.open("rb", buffering=1024 * 1024) as stream:
        if len(stream.read(4)) != 4:
            raise FormatError(f"{path}: header OTBM truncado")
        if stream.read(1) != bytes((NODE_START,)):
            raise FormatError(f"{path}: raiz OTBM ausente")
        try:
            _walk_node(stream, str(path), (x, y, z), result)
        except _TileFound:
            pass
    for stack_position, item in enumerate(result["items"], start=1):
        item["stack_position"] = stack_position
        item["stack_position_zero_based"] = stack_position - 1
    return result


def inspect_map_position(root: Path, x: int, y: int, z: int) -> dict[str, object]:
    root = root.resolve()
    layout = require_asset_layout(root)
    maps = sorted(layout["world"].glob("*.otbm"))
    if len(maps) != 1:
        raise FormatError(f"esperado um mapa canônico; encontrados {len(maps)}")
    otb_paths = sorted(layout["items"].glob("*.otb"))
    if len(otb_paths) != 1:
        raise FormatError(f"esperado um items.otb; encontrados {len(otb_paths)}")
    report = inspect_position_file(maps[0], x, y, z)
    mappings = read_otb_items(otb_paths[0])
    otfi_paths = sorted(layout["860"].glob("*.otfi"))
    dat_paths = sorted(layout["860"].glob("*.dat"))
    if len(otfi_paths) != 1 or len(dat_paths) != 1:
        raise FormatError("esperado exatamente um OTFI e um DAT em assets/860")
    otfi = parse_otfi(otfi_paths[0])
    dat_flags = dat_item_flags(dat_paths[0].read_bytes(), otfi, str(dat_paths[0]))
    for item in report["items"]:
        metadata = mappings.get(item["server_id"])
        if metadata:
            item["client_id"] = metadata["client_id"]
            item["otb_group"] = metadata["group"]
            item["otb_flags_mask"] = f"0x{metadata['flags']:08X}"
            item["otb_flags"] = flag_names(metadata["flags"])
            client_flags = dat_flags.get(metadata["client_id"])
            if client_flags is not None:
                item["dat_flags"] = dat_flag_names(client_flags)
        else:
            item["otb_mapping_missing"] = True
    report["passed"] = True
    report["errors"] = []
    return report
