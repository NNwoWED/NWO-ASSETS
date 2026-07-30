from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import struct

from .binary import BinaryReader
from .errors import FormatError


NODE_START = 0xFE
NODE_END = 0xFF
ESCAPE = 0xFD

ATTR_NAMES = {
    0x10: "server_id",
    0x11: "client_id",
    0x12: "name",
    0x14: "ground_speed",
    0x20: "sprite_hash",
    0x21: "minimap_color",
    0x22: "max_read_write_chars",
    0x23: "max_read_chars",
    0x2A: "light",
    0x2B: "stack_order",
    0x2D: "trade_as",
}


@dataclass
class OtbNode:
    data: bytes
    children: list["OtbNode"]


def _parse_node(data: bytes, position: int, source: str) -> tuple[OtbNode, int]:
    if position >= len(data) or data[position] != NODE_START:
        found = "<eof>" if position >= len(data) else f"0x{data[position]:02X}"
        raise FormatError(
            f"{source}: início de nó OTB esperado no offset {position}; encontrado {found}"
        )
    position += 1
    node_data = bytearray()
    children: list[OtbNode] = []
    while position < len(data):
        value = data[position]
        position += 1
        if value == ESCAPE:
            if position >= len(data):
                raise FormatError(f"{source}: escape truncado no fim do arquivo")
            node_data.append(data[position])
            position += 1
        elif value == NODE_START:
            child, position = _parse_node(data, position - 1, source)
            children.append(child)
        elif value == NODE_END:
            return OtbNode(bytes(node_data), children), position
        else:
            node_data.append(value)
    raise FormatError(f"{source}: nó OTB sem marcador de fechamento")


def parse_otb_tree(path: Path) -> tuple[int, OtbNode]:
    data = path.read_bytes()
    if len(data) < 5:
        raise FormatError(f"{path}: OTB truncado")
    file_version = struct.unpack_from("<I", data, 0)[0]
    root, end = _parse_node(data, 4, str(path))
    if end != len(data):
        raise FormatError(
            f"{path}: {len(data) - end} bytes após o fechamento do nó raiz"
        )
    return file_version, root


def inspect_otb(path: Path) -> dict[str, object]:
    file_version, root = parse_otb_tree(path)
    root_reader = BinaryReader(root.data, source=f"{path}:root")
    root_type = root_reader.u8()
    flags = root_reader.u32()
    version_attribute = root_reader.u8()
    version_length = root_reader.u16()
    if version_length != 140:
        raise FormatError(
            f"{path}: header de versão OTB tem {version_length} bytes, esperado 140"
        )
    major = root_reader.u32()
    minor = root_reader.u32()
    build = root_reader.u32()
    csd_raw = root_reader.bytes(128)
    csd_version = csd_raw.split(b"\0", 1)[0].decode("latin-1", errors="replace")
    if root_reader.remaining:
        raise FormatError(
            f"{path}: {root_reader.remaining} bytes desconhecidos no nó raiz OTB"
        )

    server_ids: list[int] = []
    client_ids: list[int] = []
    identity_mappings = 0
    groups: Counter[int] = Counter()
    attribute_counts: Counter[str] = Counter()
    unknown_attributes: Counter[str] = Counter()
    malformed_attributes: list[dict[str, object]] = []

    for index, node in enumerate(root.children):
        reader = BinaryReader(node.data, source=f"{path}:item-node-{index}")
        group = reader.u8()
        groups[group] += 1
        reader.u32()  # flags funcionais
        values: dict[str, object] = {}
        while reader.remaining:
            attribute = reader.u8()
            length = reader.u16()
            payload = reader.bytes(length)
            name = ATTR_NAMES.get(attribute)
            if name is None:
                name = f"0x{attribute:02X}"
                unknown_attributes[name] += 1
            attribute_counts[name] += 1
            if attribute in {0x10, 0x11}:
                if length != 2:
                    malformed_attributes.append(
                        {"node": index, "attribute": name, "length": length}
                    )
                elif attribute == 0x10:
                    values["server_id"] = struct.unpack("<H", payload)[0]
                else:
                    values["client_id"] = struct.unpack("<H", payload)[0]
            elif attribute == 0x20 and length != 16:
                malformed_attributes.append(
                    {"node": index, "attribute": name, "length": length}
                )
        server_id = values.get("server_id")
        client_id = values.get("client_id")
        if isinstance(server_id, int):
            server_ids.append(server_id)
        if isinstance(client_id, int):
            client_ids.append(client_id)
        if server_id is not None and server_id == client_id:
            identity_mappings += 1
    server_duplicates = sorted(
        value for value, count in Counter(server_ids).items() if count > 1
    )
    client_duplicates = sorted(
        value for value, count in Counter(client_ids).items() if count > 1
    )
    server_gaps: list[int] = []
    if server_ids:
        present = set(server_ids)
        server_gaps = [
            value
            for value in range(min(server_ids), max(server_ids) + 1)
            if value not in present
        ]

    return {
        "path": str(path),
        "size": path.stat().st_size,
        "file_version": file_version,
        "root_type": root_type,
        "root_flags": flags,
        "root_version_attribute": version_attribute,
        "version": {
            "major": major,
            "minor": minor,
            "build": build,
            "csd": csd_version,
        },
        "item_nodes": len(root.children),
        "groups": {str(key): value for key, value in sorted(groups.items())},
        "attribute_counts": dict(sorted(attribute_counts.items())),
        "unknown_attributes": dict(sorted(unknown_attributes.items())),
        "malformed_attributes": malformed_attributes[:50],
        "server_ids": {
            "count": len(server_ids),
            "min": min(server_ids, default=None),
            "max": max(server_ids, default=None),
            "duplicates": server_duplicates[:50],
            "gap_count": len(server_gaps),
            "gaps_sample": server_gaps[:50],
        },
        "client_ids": {
            "count": len(client_ids),
            "min": min(client_ids, default=None),
            "max": max(client_ids, default=None),
            "duplicates": client_duplicates[:50],
        },
        "identity_mappings": identity_mappings,
    }
