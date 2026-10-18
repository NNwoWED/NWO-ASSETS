"""Lossless, bounded OTBM v2 editing and node-event JSONL conversion.

Only explicitly selected tile nodes are replaced. All other source bytes, including
unknown metadata, non-canonical escapes, item attributes and container children,
are copied verbatim. This low-level codec never publishes the canonical map: the
caller must perform versioning/validation and explicit canonical publication.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
from array import array
from pathlib import Path
import base64
import binascii
import gzip
import hashlib
import heapq
import json
import mmap
import os
import re
import struct
import tempfile

START, END, ESCAPE = 254, 255, 253
TOKENS = re.compile(b"\xfd.|[\xfe\xff]", re.DOTALL)
UNESCAPE = re.compile(b"\xfd(.)", re.DOTALL)
MAX_BYTES = 16 * 1024**3
MAX_NODES = 200_000_000
MAX_DEPTH = 128
MAX_HEADER = 16 * 1024**2
MAX_TILE = 32 * 1024**2
MAX_CHANGES = 16_777_216
MAX_COORDINATE_INDEX_BYTES = 256 * 1024**2
JSONL_FORMAT = "nwo-otbm-node-events"
JSONL_SCHEMA = 1


class MapEditError(ValueError):
    """Invalid/unsupported input; no destination was committed."""


class Cancelled(MapEditError):
    """User cancellation; no destination was committed."""


def _cancel(cancel):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise Cancelled("Operação OTBM cancelada; destino preservado.")


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise MapEditError(f"{name} deve ser inteiro entre {low} e {high}.")
    return value


def _position(position):
    if not isinstance(position, (list, tuple)) or len(position) != 3:
        raise MapEditError("Coordenada deve conter x, y e z.")
    return (_integer(position[0], 0, 65535, "x"),
            _integer(position[1], 0, 65535, "y"),
            _integer(position[2], 0, 15, "z"))


def _escape(payload):
    return payload.replace(b"\xfd", b"\xfd\xfd").replace(b"\xfe", b"\xfd\xfe").replace(b"\xff", b"\xfd\xff")


def _unescape(raw):
    if len(raw) > MAX_HEADER:
        raise MapEditError("Cabeçalho de nó excede o limite seguro.")
    if raw.endswith(b"\xfd"):
        # A final FD is valid only when it is the escaped byte of FD FD.
        count = len(raw) - len(raw.rstrip(b"\xfd"))
        if count % 2:
            raise MapEditError("Escape OTBM truncado.")
    return UNESCAPE.sub(lambda match: match[1], raw) if b"\xfd" in raw else raw


def _node(payload, children=b""):
    return b"\xfe" + _escape(payload) + children + b"\xff"


def _check_tile_header(payload):
    """Check known prefix attributes; unknown lengths remain opaque/protected."""
    cursor = 7 if payload[0] == 14 else 3
    while cursor < len(payload):
        attr = payload[cursor]
        cursor += 1
        if attr == 9:
            if cursor + 2 > len(payload) or struct.unpack_from("<H", payload, cursor)[0] == 0:
                raise MapEditError("Item inline truncado ou Server ID zero.")
            cursor += 2
        elif attr == 3:
            if cursor + 4 > len(payload):
                raise MapEditError("Flags do tile truncadas.")
            cursor += 4
        else:
            return


def node_events(data, start=4, *, cancel=None, exact=True):
    """Yield (opening, offset, decoded_header, raw_escaped_header).

    The iterator validates balanced nodes, nonempty types, depth/count/header
    bounds, absence of data after children, and (by default) no trailing bytes.
    It does not materialize the tree. ``exact=False`` reads one subtree only.
    """
    if type(start) is not int or not 0 <= start < len(data) or data[start] != START:
        raise MapEditError("Abertura de nó OTBM ausente.")
    _cancel(cancel)
    pending, depth, count, after_close = None, 0, 0, None
    for token in TOKENS.finditer(data, start):
        pos, marker = token.start(), token[0][0]
        if marker == ESCAPE:
            if after_close is not None:
                raise MapEditError("Dados após filhos de um nó OTBM.")
            continue
        if after_close is not None and pos != after_close:
            raise MapEditError("Dados após filhos de um nó OTBM.")
        after_close = None
        if pending is not None:
            if pos - pending - 1 > MAX_HEADER:
                raise MapEditError("Cabeçalho de nó excede o limite seguro.")
            raw = bytes(data[pending + 1:pos])
            payload = _unescape(raw)
            if not payload:
                raise MapEditError("Nó OTBM vazio.")
            yield True, pending, payload, raw
            pending = None
        if marker == START:
            depth += 1
            count += 1
            if depth > MAX_DEPTH or count > MAX_NODES:
                raise MapEditError("Árvore OTBM excede limite de profundidade/nós.")
            pending = pos
            if count % 8192 == 0:
                _cancel(cancel)
        else:
            depth -= 1
            if depth < 0:
                raise MapEditError("Fechamento OTBM sem abertura.")
            yield False, pos, b"", b""
            if not depth:
                if exact and pos != len(data) - 1:
                    raise MapEditError("Dados adicionais após a raiz OTBM.")
                _cancel(cancel)
                return
            after_close = pos + 1
    raise MapEditError("Árvore OTBM truncada.")


def tile_record(data, offset=0):
    """Read one tile subtree, preserving its complete raw byte representation.

    ``items`` contains only inline and direct-child SIDs (not container content).
    Unknown attributes/nodes are preserved but conservatively mark it protected.
    ``end`` is exclusive, ``dx/dy`` belong to the original tile-area origin.
    """
    stack, items, reasons = [], [], set()
    house, flags, header, end = None, 0, None, None
    for opening, pos, payload, _ in node_events(data, offset, exact=False):
        if pos - offset > MAX_TILE:
            raise MapEditError("Tile excede o limite seguro de tamanho.")
        if opening:
            kind = payload[0]
            parent = stack[-1] if stack else None
            stack.append(kind)
            if header is None:
                header = payload
                if kind not in (5, 14) or len(payload) < (7 if kind == 14 else 3):
                    raise MapEditError("Nó não é um tile válido.")
                cursor = 7 if kind == 14 else 3
                if kind == 14:
                    house = struct.unpack_from("<I", payload, 3)[0]
                    reasons.add("house")
                while cursor < len(payload):
                    attr = payload[cursor]
                    cursor += 1
                    if attr == 9:
                        if cursor + 2 > len(payload):
                            raise MapEditError("Item inline truncado.")
                        sid = struct.unpack_from("<H", payload, cursor)[0]
                        if sid == 0:
                            raise MapEditError("Server ID zero no tile.")
                        items.append(sid)
                        cursor += 2
                    elif attr == 3:
                        if cursor + 4 > len(payload):
                            raise MapEditError("Flags do tile truncadas.")
                        flags = struct.unpack_from("<I", payload, cursor)[0]
                        cursor += 4
                        reasons.add("flags")
                    else:
                        reasons.add("unknownTileAttributes")
                        break  # Unknown payload length: never guess its layout.
            else:
                if kind != 6:
                    reasons.add("unknownChildNodes")
                elif len(payload) < 3:
                    raise MapEditError("Item truncado.")
                else:
                    sid = struct.unpack_from("<H", payload, 1)[0]
                    if sid == 0:
                        raise MapEditError("Server ID zero no item.")
                    if len(stack) == 2 and parent in (5, 14):
                        items.append(sid)
                    if len(payload) > 3:
                        reasons.add("itemAttributes")
                if len(stack) > 2:
                    reasons.add("nestedItems")
        else:
            stack.pop()
            if not stack:
                end = pos + 1
    return {"raw": bytes(data[offset:end]), "end": end, "items": items,
            "house": house, "flags": flags, "protected": bool(reasons),
            "protectionReasons": sorted(reasons), "dx": header[1], "dy": header[2]}


def build_tile(x, y, z, items, flags=0):
    """Build a simple tile relative to its aligned 256-SQM area (not a map)."""
    x, y, z = _position((x, y, z))
    _integer(flags, 0, 0xFFFFFFFF, "flags")
    if not isinstance(items, (tuple, list)) or len(items) > 65535:
        raise MapEditError("Lista de itens inválida ou excessiva.")
    children = bytearray()
    for sid in items:
        _integer(sid, 1, 65535, "Server ID")
        children.extend(_node(b"\x06" + struct.pack("<H", sid)))
    payload = bytes((5, x % 256, y % 256))
    if flags:
        payload += b"\x03" + struct.pack("<I", flags)
    return _node(payload, bytes(children))


def rebase_tile(raw, x, y, z, area_x=None, area_y=None):
    """Change only dx/dy, retaining the remainder of the encoded subtree."""
    x, y, z = _position((x, y, z))
    ax = x // 256 * 256 if area_x is None else _integer(area_x, 0, 65535, "area_x")
    ay = y // 256 * 256 if area_y is None else _integer(area_y, 0, 65535, "area_y")
    if not (0 <= x - ax <= 255 and 0 <= y - ay <= 255):
        raise MapEditError("Tile não cabe na origem da área solicitada.")
    rec = tile_record(raw)
    if rec["end"] != len(raw):
        raise MapEditError("Dados adicionais após o tile.")
    cursor = 1
    for _ in range(3):
        cursor += 2 if raw[cursor] == ESCAPE else 1
    kind = 14 if rec["house"] is not None else 5
    return b"\xfe" + _escape(bytes((kind, x - ax, y - ay))) + raw[cursor:]


class _Coordinates:
    """Sparse 256x256 bitmaps: 8 KiB per occupied block, not a tuple per tile."""
    def __init__(self):
        self.blocks = {}

    def contains(self, x, y, z):
        bitmap = self.blocks.get((x >> 8, y >> 8, z))
        bit = (y & 255) * 256 + (x & 255)
        return bitmap is not None and bool(bitmap[bit >> 3] & (1 << (bit & 7)))

    def add(self, x, y, z):
        key = (x >> 8, y >> 8, z)
        bitmap = self.blocks.get(key)
        if bitmap is None:
            if (len(self.blocks) + 1) * 8192 > MAX_COORDINATE_INDEX_BYTES:
                raise MapEditError("Índice de coordenadas excede 256 MiB; mapa excessivamente disperso.")
            bitmap = self.blocks[key] = bytearray(8192)
        bit = (y & 255) * 256 + (x & 255)
        byte, mask = bit >> 3, 1 << (bit & 7)
        if bitmap[byte] & mask:
            raise MapEditError(f"Tile duplicado: {x}, {y}, {z}.")
        bitmap[byte] |= mask


def _scan(data, *, cancel=None, progress=None, on_tile=None, collect_areas=True):
    if len(data) < 8 or len(data) > MAX_BYTES or data[:4] not in (b"OTBM", bytes(4)):
        raise MapEditError("Assinatura/tamanho OTBM inválido.")
    stack, areas, tile, map_end = [], [], None, None
    coordinates = _Coordinates()
    count = nodes = map_nodes = area_count = 0
    root = None
    metadata = hashlib.sha256()
    metadata.update(bytes(data[:4]))

    def metadata_event(label, raw=b""):
        metadata.update(label + struct.pack("<Q", len(raw)) + raw)

    for opening, offset, payload, encoded in node_events(data, cancel=cancel):
        if opening:
            nodes += 1
            kind = payload[0]
            parent = stack[-1][0] if stack else None
            if parent is None:
                if kind != 0 or len(payload) < 17:
                    raise MapEditError("Cabeçalho raiz OTBM inválido.")
                version, width, height, major, minor = struct.unpack_from("<IHHII", payload, 1)
                if version != 2:
                    raise MapEditError("Somente OTBM versão 2 é suportado; não há conversão de versões por troca de header.")
                root = {"version": version, "width": width, "height": height,
                        "itemsMajorVersion": major, "itemsMinorVersion": minor}
            elif kind == 2:
                if parent != 0 or len(stack) != 1:
                    raise MapEditError("Map data fora da raiz.")
                map_nodes += 1
                if map_nodes > 1:
                    raise MapEditError("Map data duplicado.")
            elif kind == 4:
                if parent != 2 or len(payload) < 6:
                    raise MapEditError("Área OTBM sem map data ou truncada.")
                ax, ay, az = struct.unpack_from("<HHB", payload, 1)
                _position((ax, ay, az))
                area_count += 1
                areas.append({"x": ax, "y": ay, "z": az, "start": offset, "end": None})
            elif kind in (5, 14):
                if parent != 4 or len(payload) < (7 if kind == 14 else 3) or tile is not None:
                    raise MapEditError("Tile sem área ou truncado.")
                area = areas[stack[-1][2]]
                xyz = _position((area["x"] + payload[1], area["y"] + payload[2], area["z"]))
                coordinates.add(*xyz)
                _check_tile_header(payload)
                tile = (xyz, offset, stack[-1][2])
            elif kind == 6 and (len(payload) < 3 or struct.unpack_from("<H", payload, 1)[0] == 0):
                raise MapEditError("Item OTBM truncado ou Server ID zero.")
            if tile is None:
                if kind == 4:
                    if len(payload) > 6:
                        cursor = 0
                        for _ in range(6):
                            cursor += 2 if encoded[cursor] == ESCAPE else 1
                        metadata_event(b"A", payload[1:6] + encoded[cursor:])
                else:
                    # Unknown non-tile data under an area may use its origin.
                    # Moving it is a metadata change even if its bytes match.
                    context_area = next((entry for entry in reversed(stack) if entry[0] == 4), None)
                    if context_area is not None:
                        context = areas[context_area[2]]
                        metadata_event(b"C", struct.pack("<HHB", context["x"], context["y"], context["z"]))
                    metadata_event(b"S", encoded)
            stack.append((kind, offset, len(areas) - 1 if kind == 4 else None))
        else:
            kind, _, area_idx = stack.pop()
            if tile is None and kind != 4:
                metadata_event(b"E")
            if kind in (5, 14):
                count += 1
                if on_tile:
                    on_tile(tile[0], tile[1], offset + 1, areas[tile[2]])
                tile = None
                if count % 16384 == 0 and progress:
                    progress(offset / len(data), count)
            elif kind == 4:
                areas[area_idx]["end"] = offset
                if not collect_areas:
                    areas.clear()
            elif kind == 2:
                map_end = offset
    if map_nodes != 1:
        raise MapEditError("OTBM deve conter exatamente um nó map data.")
    _cancel(cancel)
    if progress:
        progress(1.0, count)
    return {**root, "tiles": count, "nodes": nodes, "tileAreas": area_count,
            "bytes": len(data), "areas": areas, "mapDataEnd": map_end,
            "metadataHash": metadata.hexdigest()}


def iter_tile_records(path_or_data, *, cancel=None, progress=None):
    """Yield full tile records from a path, bytes or read-only mmap.

    Exhaust the iterator to validate the complete map. Memory is proportional to
    occupied 256x256 bitmap blocks and current tile, never the total tile count.
    ``raw`` here uses the ORIGINAL area origin; call rebase_tile(raw,x,y,z) to
    normalize it before supplying it to rewrite_map or a coordinate-based diff.
    """
    if isinstance(path_or_data, (str, os.PathLike)):
        with _mapped(path_or_data) as data:
            yield from iter_tile_records(data, cancel=cancel, progress=progress)
        return
    data = path_or_data
    if len(data) < 8 or len(data) > MAX_BYTES or data[:4] not in (b"OTBM", bytes(4)):
        raise MapEditError("Assinatura/tamanho OTBM inválido.")
    stack, area, tile = [], None, None
    coordinates, count, map_nodes = _Coordinates(), 0, 0
    for opening, offset, payload, _ in node_events(data, cancel=cancel):
        if opening:
            kind = payload[0]
            parent = stack[-1] if stack else None
            if parent is None:
                if kind != 0 or len(payload) < 17 or struct.unpack_from("<I", payload, 1)[0] != 2:
                    raise MapEditError("Raiz inválida: somente OTBM versão 2 é suportado.")
            elif kind == 2:
                if parent != 0 or len(stack) != 1:
                    raise MapEditError("Map data fora da raiz.")
                map_nodes += 1
                if map_nodes > 1:
                    raise MapEditError("Map data duplicado.")
            elif kind == 4:
                if parent != 2 or len(payload) < 6:
                    raise MapEditError("Área inválida.")
                area = _position(struct.unpack_from("<HHB", payload, 1))
            elif kind in (5, 14):
                if parent != 4 or area is None or len(payload) < (7 if kind == 14 else 3) or tile is not None:
                    raise MapEditError("Tile fora de área ou truncado.")
                xyz = _position((area[0] + payload[1], area[1] + payload[2], area[2]))
                coordinates.add(*xyz)
                _check_tile_header(payload)
                tile = (xyz, offset, area)
            elif kind == 6 and (len(payload) < 3 or struct.unpack_from("<H", payload, 1)[0] == 0):
                raise MapEditError("Item truncado ou Server ID zero.")
            stack.append(kind)
        else:
            kind = stack.pop()
            if kind in (5, 14):
                xyz, begin, origin = tile
                rec = tile_record(data, begin)
                count += 1
                yield {**rec, "x": xyz[0], "y": xyz[1], "z": xyz[2],
                       "offset": begin, "areaX": origin[0], "areaY": origin[1]}
                tile = None
                if count % 16384 == 0 and progress:
                    progress(offset / len(data), count)
            elif kind == 4:
                area = None
    if map_nodes != 1:
        raise MapEditError("OTBM deve conter exatamente um map data.")
    _cancel(cancel)
    if progress:
        progress(1.0, count)


@contextmanager
def _mapped(path):
    path = Path(path)
    with path.open("rb") as source:
        size = os.fstat(source.fileno()).st_size
        if not 8 <= size <= MAX_BYTES:
            raise MapEditError("Tamanho de mapa inválido ou maior que 16 GiB.")
        with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            yield data


def _sha(data, cancel=None):
    result = hashlib.sha256()
    for offset in range(0, len(data), 4 * 1024**2):
        _cancel(cancel)
        result.update(data[offset:offset + 4 * 1024**2])
    return result.hexdigest()


def inspect_map(path, *, cancel=None, progress=None):
    """Validate source structure/coordinates and return public metadata + SHA256."""
    with _mapped(path) as data:
        report = _scan(data, cancel=cancel, progress=progress, collect_areas=False)
        report.pop("areas")
        report.pop("mapDataEnd")
        report["sha256"] = _sha(data, cancel)
        report["signature"] = bytes(data[:4]).hex()
        return report


def _paths(source, dest, overwrite):
    source, dest = Path(source).resolve(), Path(dest).resolve()
    if source == dest or (dest.exists() and os.path.samefile(source, dest)):
        raise MapEditError("Origem e destino devem ser arquivos diferentes.")
    if dest.exists() and not overwrite:
        raise FileExistsError(f"Destino já existe: {dest}")
    if not dest.parent.is_dir():
        raise MapEditError("Diretório de destino não existe.")
    return source, dest


@contextmanager
def _temporary(dest):
    fd, name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    os.close(fd)
    path = Path(name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _publish(temp, dest, overwrite):
    # Hard-link creation is atomic and fails if a destination raced into existence.
    # overwrite=True is explicit; os.replace never exposes a partly written file.
    if overwrite:
        os.replace(temp, dest)
    else:
        os.link(temp, dest)
        temp.unlink()


def _copy_slice(data, output, begin, end, cancel):
    for cursor in range(begin, end, 4 * 1024**2):
        _cancel(cancel)
        output.write(data[cursor:min(cursor + 4 * 1024**2, end)])


def _changes_hash(changes, cancel=None, *, validate=False):
    """Fingerprint a stable Mapping without retaining its values or tuple keys."""
    if not isinstance(changes, Mapping) or len(changes) > MAX_CHANGES:
        raise MapEditError("Mudanças devem ser um Mapping de até 16.777.216 coordenadas.")
    digest = hashlib.sha256()
    seen = _Coordinates() if validate else None
    count = 0
    for coord, raw in changes.items():
        if count % 4096 == 0:
            _cancel(cancel)
        xyz = _position(coord)
        if seen is not None:
            seen.add(*xyz)
        if raw is not None:
            if not isinstance(raw, bytes) or len(raw) > MAX_TILE:
                raise MapEditError("Mudança de tile deve conter bytes ou None.")
            if validate:
                rec = tile_record(raw)
                if rec["end"] != len(raw) or (rec["dx"], rec["dy"]) != (xyz[0] % 256, xyz[1] % 256):
                    raise MapEditError("Tile de mudança não corresponde à coordenada alinhada.")
        digest.update(struct.pack("<HHBq", *xyz, -1 if raw is None else len(raw)))
        if raw is not None:
            digest.update(raw)
        count += 1
        if count > len(changes):
            raise MapEditError("Mapping de mudanças contém mais entradas que o tamanho declarado.")
    if count != len(changes):
        raise MapEditError("Mapping de mudanças diverge do tamanho declarado.")
    return digest.hexdigest()


def rewrite_map(source, dest, changes, *, cancel=None, progress=None, overwrite=False):
    """Atomically replace/delete tiles and insert missing tiles in a distinct map.

    ``changes`` maps absolute (x,y,z) to complete tile bytes or None (delete).
    Byte inputs must be aligned-area relative as produced by build_tile/rebase_tile.
    Existing areas may be unaligned or split; the writer uses each tile's actual
    original origin. Untouched bytes are never reserialized. Protected-tile policy
    is the caller's responsibility (tile_record reports it explicitly).
    """
    source, dest = _paths(source, dest, overwrite)
    changes_hash = _changes_hash(changes, cancel, validate=True)
    pending = changes  # Lazy Mapping is supported; never make a second raw dictionary.
    _cancel(cancel)
    # 32 bytes per replacement, rather than tuple + coordinates + copied tile bytes.
    # Source traversal already supplies sorted offsets, so no large sort is needed.
    existing_patches, insert_patches, found = array("Q"), [], _Coordinates()
    changed = deleted = unchanged = 0
    with _mapped(source) as data:
        before_hash = _sha(data, cancel)

        def visit(xyz, begin, end, area):
            nonlocal changed, deleted, unchanged
            if xyz not in pending:
                return
            found.add(*xyz)
            raw = pending[xyz]
            replacement = b"" if raw is None else rebase_tile(raw, *xyz, area["x"], area["y"])
            if replacement == data[begin:end]:
                unchanged += 1
                return
            code = xyz[0] | xyz[1] << 16 | xyz[2] << 32
            origin = area["x"] | area["y"] << 16
            existing_patches.extend((begin, end, code, origin))
            if raw is None:
                deleted += 1
            else:
                changed += 1

        report = _scan(data, cancel=cancel, progress=progress, on_tile=visit)
        area_buckets = defaultdict(list)
        if len(pending) > changed + deleted + unchanged:
            for area in report["areas"]:
                for bx in range(area["x"] // 256, min(65535, area["x"] + 255) // 256 + 1):
                    for by in range(area["y"] // 256, min(65535, area["y"] + 255) // 256 + 1):
                        area_buckets[(bx, by, area["z"])].append(area)
        insertions, new_areas = defaultdict(bytearray), defaultdict(bytearray)
        inserted = missing_deletes = 0
        for index, xyz in enumerate(pending):
            if index % 4096 == 0:
                _cancel(cancel)
            if found.contains(*xyz):
                continue
            raw = pending[xyz]
            if raw is None:
                missing_deletes += 1
                continue
            x, y, z = xyz
            bucket = (x // 256, y // 256, z)
            area = next((a for a in area_buckets[bucket]
                         if a["x"] <= x <= a["x"] + 255 and a["y"] <= y <= a["y"] + 255), None)
            if area:
                insertions[area["end"]].extend(rebase_tile(raw, x, y, z, area["x"], area["y"]))
            else:
                new_areas[bucket].extend(raw)
            inserted += 1
        for offset, payload in insertions.items():
            insert_patches.append((offset, offset, payload))
        new_area_count = len(new_areas)
        if new_areas:
            payload = bytearray()
            for (bx, by, z), tiles in sorted(new_areas.items()):
                payload.extend(_node(b"\x04" + struct.pack("<HHB", bx * 256, by * 256, z), bytes(tiles)))
            insert_patches.append((report["mapDataEnd"], report["mapDataEnd"], payload))
        insert_patches.sort(key=lambda patch: (patch[0], patch[1]))
        # Drop source-area and insertion work tables before output validation builds
        # its own index. Do not retain two complete area inventories at once.
        report.pop("areas")
        del area_buckets, found, insertions, new_areas

        def replacement_patches():
            for index in range(0, len(existing_patches), 4):
                if index % 16384 == 0:
                    _cancel(cancel)
                begin, end, code, origin = existing_patches[index:index + 4]
                xyz = (code & 65535, (code >> 16) & 65535, code >> 32)
                raw = pending[xyz]
                replacement = b"" if raw is None else rebase_tile(raw, *xyz, origin & 65535, origin >> 16)
                yield begin, end, replacement

        with _temporary(dest) as temp:
            with temp.open("wb") as output:
                cursor = 0
                for begin, end, replacement in heapq.merge(replacement_patches(), insert_patches,
                                                          key=lambda patch: (patch[0], patch[1])):
                    if begin < cursor:
                        raise MapEditError("Intervalos de alteração sobrepostos.")
                    _copy_slice(data, output, cursor, begin, cancel)
                    output.write(replacement)
                    cursor = end
                _copy_slice(data, output, cursor, len(data), cancel)
                output.flush()
                os.fsync(output.fileno())
            output_report = inspect_map(temp, cancel=cancel)
            if output_report["tiles"] != report["tiles"] + inserted - deleted:
                raise MapEditError("Contagem de tiles divergente após escrita.")
            if _sha(data, cancel) != before_hash:
                raise MapEditError("Origem mudou durante a operação; destino não publicado.")
            if _changes_hash(pending, cancel) != changes_hash:
                raise MapEditError("Mudanças foram alteradas durante a operação; destino não publicado.")
            _cancel(cancel)
            _publish(temp, dest, overwrite)
    return {"sourceSha256": before_hash, "sha256": output_report["sha256"],
            "changed": changed, "deleted": deleted, "inserted": inserted,
            "unchanged": unchanged, "missingDeletes": missing_deletes,
            "newAreas": new_area_count, "tiles": output_report["tiles"],
            "bytes": output_report["bytes"], "committed": True}


def _json_write(output, value):
    output.write(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n")


def export_jsonl(source, dest, *, gzip_output=None, cancel=None, progress=None, overwrite=False):
    """Export OTBM2 as lossless escaped-node events (plain JSONL or gzip)."""
    source, dest = _paths(source, dest, overwrite)
    zipped = dest.suffix.lower() == ".gz" if gzip_output is None else bool(gzip_output)
    with _mapped(source) as data:
        metadata = _scan(data, cancel=cancel, progress=progress, collect_areas=False)
        source_hash = _sha(data, cancel)
        manifest = {"format": JSONL_FORMAT, "schema": JSONL_SCHEMA,
                    "signatureHex": bytes(data[:4]).hex(), "otbmVersion": 2,
                    "bytes": len(data), "sha256": source_hash, "nodes": metadata["nodes"]}
        with _temporary(dest) as temp:
            with temp.open("wb") as file:
                output = gzip.GzipFile(fileobj=file, mode="wb", mtime=0, filename="") if zipped else file
                try:
                    _json_write(output, {"event": "manifest", **manifest})
                    events = 0
                    for opening, offset, _, raw in node_events(data, cancel=cancel):
                        _json_write(output, {"event": "start", "raw": base64.b64encode(raw).decode("ascii")} if opening else {"event": "end"})
                        events += 1
                        if events % 16384 == 0 and progress:
                            progress(offset / len(data), events)
                    _json_write(output, {"event": "complete", "events": events, "sha256": source_hash})
                finally:
                    if zipped:
                        output.close()
                file.flush()
                os.fsync(file.fileno())
            if _sha(data, cancel) != source_hash:
                raise MapEditError("Origem mudou durante a conversão.")
            _cancel(cancel)
            _publish(temp, dest, overwrite)
    return {**manifest, "gzip": zipped, "committed": True}


def _json_line(stream):
    # base64 header is at most 4/3 MAX_HEADER, plus JSON envelope.
    limit = MAX_HEADER * 4 // 3 + 4096
    line = stream.readline(limit + 1)
    if not line:
        return None
    if len(line) > limit or not line.endswith(b"\n"):
        raise MapEditError("Linha JSONL excessiva ou truncada.")
    try:
        result = json.loads(line)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise MapEditError("JSONL inválido.") from exc
    if not isinstance(result, dict):
        raise MapEditError("Evento JSONL deve ser objeto.")
    return result


def import_jsonl(source, dest, *, cancel=None, progress=None, overwrite=False):
    """Restore an exact OTBM2 binary after manifest/hash/structure verification.

    SHA256 is mandatory: this is a lossless converter, not an unvalidated JSON
    map editor. Changes should go through rewrite_map and its tile validation.
    gzip is detected by magic bytes, not by user-controlled file extension.
    """
    source, dest = _paths(source, dest, overwrite)
    _cancel(cancel)
    with source.open("rb") as file:
        zipped = file.read(2) == b"\x1f\x8b"
        file.seek(0)
        stream = gzip.GzipFile(fileobj=file, mode="rb") if zipped else file
        try:
            manifest = _json_line(stream)
            if (not manifest or manifest.get("event") != "manifest" or
                    manifest.get("format") != JSONL_FORMAT or manifest.get("schema") != JSONL_SCHEMA or
                    manifest.get("otbmVersion") != 2):
                raise MapEditError("Manifesto de conversão OTBM2 ausente/incompatível.")
            expected_bytes = _integer(manifest.get("bytes"), 8, MAX_BYTES, "bytes")
            expected_nodes = _integer(manifest.get("nodes"), 1, MAX_NODES, "nodes")
            signature = manifest.get("signatureHex")
            if signature not in ("00000000", "4f54424d"):
                raise MapEditError("Assinatura do manifesto inválida.")
            expected_hash = manifest.get("sha256")
            if not isinstance(expected_hash, str) or not re.fullmatch("[0-9a-f]{64}", expected_hash):
                raise MapEditError("Hash SHA256 obrigatório no manifesto.")
            with _temporary(dest) as temp:
                digest, size, depth, nodes, roots, events = hashlib.sha256(), 0, 0, 0, 0, 0
                with temp.open("wb") as output:
                    def put(raw):
                        nonlocal size
                        size += len(raw)
                        if size > expected_bytes:
                            raise MapEditError("Conteúdo excede tamanho declarado no manifesto.")
                        output.write(raw)
                        digest.update(raw)
                    put(bytes.fromhex(signature))
                    while True:
                        doc = _json_line(stream)
                        if doc is None:
                            raise MapEditError("JSONL sem marcador final.")
                        if events % 8192 == 0:
                            _cancel(cancel)
                        event = doc.get("event")
                        if event == "complete":
                            if depth or roots != 1 or doc.get("events") != events or doc.get("sha256") != expected_hash:
                                raise MapEditError("Marcador final JSONL inconsistente.")
                            if _json_line(stream) is not None:
                                raise MapEditError("Dados adicionais após marcador final JSONL.")
                            break
                        if event == "start":
                            raw_text = doc.get("raw")
                            if not isinstance(raw_text, str) or len(raw_text) > MAX_HEADER * 4 // 3 + 4:
                                raise MapEditError("Payload de nó JSONL inválido.")
                            try:
                                raw = base64.b64decode(raw_text, validate=True)
                            except (ValueError, binascii.Error) as exc:
                                raise MapEditError("Base64 inválido no nó JSONL.") from exc
                            if not raw or len(raw) > MAX_HEADER:
                                raise MapEditError("Cabeçalho de nó vazio ou excessivo.")
                            # A payload must contain escaped data only, never delimiters.
                            for match in TOKENS.finditer(raw):
                                if match[0][0] != ESCAPE:
                                    raise MapEditError("Delimitador estrutural dentro do payload JSONL.")
                            _unescape(raw)
                            if depth == 0:
                                roots += 1
                            depth += 1
                            nodes += 1
                            if roots > 1 or depth > MAX_DEPTH or nodes > expected_nodes:
                                raise MapEditError("Estrutura JSONL excede os limites do manifesto.")
                            put(b"\xfe" + raw)
                        elif event == "end":
                            if depth == 0:
                                raise MapEditError("Fechamento JSONL sem abertura.")
                            depth -= 1
                            put(b"\xff")
                        else:
                            raise MapEditError("Evento JSONL desconhecido.")
                        events += 1
                        if events % 16384 == 0 and progress:
                            progress(min(1, size / expected_bytes), events)
                    if size != expected_bytes or nodes != expected_nodes or digest.hexdigest() != expected_hash:
                        raise MapEditError("Conversão diverge do tamanho, contagem ou SHA256 original.")
                    output.flush()
                    os.fsync(output.fileno())
                report = inspect_map(temp, cancel=cancel)
                _cancel(cancel)
                _publish(temp, dest, overwrite)
        except (OSError, EOFError) as exc:
            raise MapEditError(f"Falha ao ler JSONL/gzip: {exc}") from exc
        finally:
            if zipped:
                stream.close()
    return {**report, "committed": True, "exactRoundtrip": True}
