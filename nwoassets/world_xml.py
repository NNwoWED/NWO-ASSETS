"""Relocate world sidecars into a new file, preserving non-spatial content.

Spawn x/y are offsets; spawn child z is absolute (Src-Nwo/spawn.cpp).
Rectangle bounds are inclusive. A supplied rectangle mapper must return the
complete, non-overlapping image of each input box. Without one, boxes up to
one million cells are mapped exactly and compressed into horizontal/vertical
runs; mapping only corners would silently lose internal ownership boundaries.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Callable, Iterable

from .errors import FormatError

Position = tuple[int, int, int]
Rectangle = tuple[Position, Position]
MAX_DEFAULT_RECTANGLE_CELLS = 1_000_000
_XYZ = ('x', 'y', 'z')
_CENTER = ('centerx', 'centery', 'centerz')
_ENTRY = ('entryx', 'entryy', 'entryz')
_FROM = ('fromX', 'fromY', 'fromZ')
_TO = ('toX', 'toY', 'toZ')
_INT = re.compile(r'[+-]?\d+\Z')
_COORD = re.compile(r'(?:center|entry|from|to|pos|position|target|destination|start|end|map|offset)?[xyz]\Z', re.I)
_COORD_WORDS = {'position', 'pos', 'centerpos', 'frompos', 'topos', 'coordinates', 'location'}
_POINT_PATHS = {
    ('routes', 'route', 'waypoint'),
    ('areapalette', 'area', 'sub', 'apng'),
    ('areapalette', 'area', 'sub', 'soundsrc'),
    ('areapalette', 'area', 'sub', 'sound', 'soundsrc'),
}
_REGION_PATH = ('areapalette', 'area', 'sub', 'region')


class _DocumentBuilder:
    """Synthetic parent keeps comments/PIs outside the document root as well."""
    def __init__(self):
        self.builder = ET.TreeBuilder(insert_comments=True, insert_pis=True)
        self.builder.start('_world_xml_document', {})

    def start(self, tag, attrs):
        return self.builder.start(tag, attrs)

    def end(self, tag):
        return self.builder.end(tag)

    def data(self, data):
        self.builder.data(data)

    def comment(self, text):
        self.builder.comment(text)

    def pi(self, target, text):
        self.builder.pi(target, text)

    def doctype(self, name, pubid, system):
        raise FormatError('DOCTYPE não suportado em sidecar; nada foi escrito.')

    def close(self):
        self.builder.end('_world_xml_document')
        return self.builder.close()


def _parse(raw: bytes) -> tuple[ET.Element, ET.Element]:
    try:
        text = raw.decode('utf-8-sig')
        declaration = re.match(r'\s*<\?xml\s+[^?]*encoding\s*=\s*[\'\"]([^\'\"]+)', text, re.I)
        if declaration and declaration.group(1).lower().replace('-', '') != 'utf8':
            raise FormatError('Sidecar deve usar UTF-8.')
        parser = ET.XMLParser(target=_DocumentBuilder(), encoding='utf-8')
        document = ET.fromstring(text.encode('utf-8'), parser=parser)
    except (UnicodeError, ET.ParseError) as error:
        raise FormatError(f'XML UTF-8 inválido: {error}') from error
    roots = [node for node in document if isinstance(node.tag, str)]
    if len(roots) != 1 or roots[0].tag not in {'spawns', 'houses', 'routes', 'areapalette'}:
        raise FormatError('Raiz XML não suportada; esperado spawns, houses, routes ou areapalette.')
    return document, roots[0]


def _walk(node: ET.Element, path=()):
    if not isinstance(node.tag, str):
        return
    path = (*path, node.tag)
    yield node, path
    for child in node:
        yield from _walk(child, path)


def _allowed_coordinates(path: tuple[str, ...]) -> set[str]:
    if path == ('spawns', 'spawn'):
        return set(_CENTER)
    if path in {('spawns', 'spawn', 'monster'), ('spawns', 'spawn', 'npc')}:
        return set(_XYZ)
    if path == ('houses', 'house'):
        return set(_ENTRY)
    if path == _REGION_PATH:
        return set(_FROM + _TO)
    if path in _POINT_PATHS:
        return set(_XYZ) | ({'offsetX', 'offsetY'} if path[-1] == 'apng' else set())
    return set()


def _check_schema(root: ET.Element):
    for node, path in _walk(root):
        allowed = _allowed_coordinates(path)
        for attr in node.attrib:
            if (_COORD.fullmatch(attr) or attr.lower() in _COORD_WORDS) and attr not in allowed:
                raise FormatError(f'Esquema de coordenadas desconhecido em /{"/".join(path)}: {attr}')
        # Coordinates encoded as child text must never be silently left behind.
        if (node.tag.lower() in _COORD_WORDS or _COORD.fullmatch(node.tag)) and node.text and node.text.strip():
            raise FormatError(f'Coordenada textual não suportada em /{"/".join(path)}')
        if path == ('spawns', 'spawn'):
            _read_position(node, _CENTER)
            if 'radius' not in node.attrib or not _INT.fullmatch(node.attrib['radius']):
                raise FormatError('spawn requer radius inteiro; o raio não será alterado.')
        elif path == ('houses', 'house'):
            _read_position(node, _ENTRY)
        elif path in _POINT_PATHS:
            _read_position(node, _XYZ)
        elif path == _REGION_PATH:
            if len(node):
                raise FormatError('region com elementos internos não é suportada para divisão sem perda.')
            _rectangle((_read_position(node, _FROM), _read_position(node, _TO)), 'region')


def _integer(value, context: str) -> int:
    if not isinstance(value, str) or not _INT.fullmatch(value):
        raise FormatError(f'{context}: coordenada inteira obrigatória.')
    return int(value)


def _position(value, context: str) -> Position:
    try:
        result = tuple(value)
    except TypeError as error:
        raise FormatError(f'{context}: posição precisa conter três inteiros.') from error
    if len(result) != 3 or any(type(v) is not int for v in result):
        raise FormatError(f'{context}: posição precisa conter três inteiros (sem bool/float).')
    if not (0 <= result[0] <= 65535 and 0 <= result[1] <= 65535 and 0 <= result[2] <= 15):
        raise FormatError(f'{context}: posição fora dos limites OTBM: {result}')
    return result


def _read_position(node: ET.Element, keys) -> Position:
    return _position(tuple(_integer(node.get(k), f'{node.tag}.{k}') for k in keys), node.tag)


def _set_position(node: ET.Element, keys, value: Position):
    for key, number in zip(keys, value):
        if node.get(key) is None or int(node.get(key)) != number:
            node.set(key, str(number))


def _rectangle(value, context: str) -> Rectangle:
    try:
        lo, hi = value
    except (TypeError, ValueError) as error:
        raise FormatError(f'{context}: retângulo precisa de dois pontos inclusivos.') from error
    lo, hi = _position(lo, context), _position(hi, context)
    if any(a > b for a, b in zip(lo, hi)):
        raise FormatError(f'{context}: limites invertidos {lo}, {hi}.')
    return lo, hi


def _volume(rect: Rectangle) -> int:
    lo, hi = rect
    return (hi[0] - lo[0] + 1) * (hi[1] - lo[1] + 1) * (hi[2] - lo[2] + 1)


def _validate_rectangles(rectangles: list[Rectangle], expected_volume: int):
    if not rectangles or sum(map(_volume, rectangles)) != expected_volume:
        raise FormatError('rectangle_mapper perdeu ou acrescentou células ao retângulo inclusivo.')
    active = []
    for rect in sorted(rectangles, key=lambda r: r[0][0]):
        lo, hi = rect
        active = [other for other in active if other[1][0] >= lo[0]]
        for other_lo, other_hi in active:
            if all(lo[i] <= other_hi[i] and other_lo[i] <= hi[i] for i in (1, 2)):
                raise FormatError('rectangle_mapper produziu retângulos sobrepostos; mapeamento não é sem perda.')
        active.append(rect)


def _map_rectangle_exact(lo: Position, hi: Position, mapper) -> list[Rectangle]:
    if _volume((lo, hi)) > MAX_DEFAULT_RECTANGLE_CELLS:
        raise FormatError('Região grande requer rectangle_mapper explícito; limites não serão aproximados.')
    completed = []
    for z in range(lo[2], hi[2] + 1):
        active = {}
        for y in range(lo[1], hi[1] + 1):
            runs = []
            start, previous_delta = lo[0], None
            for x in range(lo[0], hi[0] + 1):
                mapped = mapper((x, y, z))
                delta = tuple(mapped[i] - (x, y, z)[i] for i in range(3))
                if previous_delta is not None and delta != previous_delta:
                    runs.append((start, x - 1, previous_delta))
                    start = x
                previous_delta = delta
            runs.append((start, hi[0], previous_delta))
            current = {}
            for x0, x1, delta in runs:
                key = (x0, x1, delta)
                low = (x0 + delta[0], y + delta[1], z + delta[2])
                high = (x1 + delta[0], y + delta[1], z + delta[2])
                current[key] = (active[key][0], high) if key in active else (low, high)
            completed.extend(rect for key, rect in active.items() if key not in current)
            active = current
        completed.extend(active.values())
    return completed


def _spawn_children(spawn: ET.Element, mapper) -> list[ET.Element]:
    center = _read_position(spawn, _CENTER)
    mapped_center = mapper(center)
    groups = []
    current = None
    current_delta = None
    pending = []
    for child in list(spawn):
        if child.tag not in {'monster', 'npc'}:
            (current if current is not None else pending).append(child)
            continue
        # The server defaults absent x/y to zero and absent z to centerz.
        ox = _integer(child.get('x', '0'), f'{child.tag}.x')
        oy = _integer(child.get('y', '0'), f'{child.tag}.y')
        az = _integer(child.get('z', str(center[2])), f'{child.tag}.z')
        absolute = _position((center[0] + ox, center[1] + oy, az), child.tag)
        target = mapper(absolute)
        delta = tuple(target[i] - absolute[i] for i in range(3))
        if current is None or delta != current_delta:
            new_center = _position(tuple(center[i] + delta[i] for i in range(3)), 'spawn traduzido')
            current = ET.Element(spawn.tag, dict(spawn.attrib))
            _set_position(current, _CENTER, new_center)
            current_delta = delta
            if not groups:
                current.text = spawn.text
                current.extend(pending)
            groups.append(current)
        # x/y offsets stay byte-for-byte unchanged within a translation run.
        if 'z' in child.attrib and int(child.get('z')) != target[2]:
            child.set('z', str(target[2]))
        current.append(child)
    if not groups:
        _set_position(spawn, _CENTER, mapped_center)
        return [spawn]
    groups[-1].tail = spawn.tail
    return groups


def _counts(document: ET.Element) -> dict:
    tags = Counter()
    volume = 0
    for node in document.iter():
        if node is document:
            continue
        name = node.tag if isinstance(node.tag, str) else '#comment' if node.tag is ET.Comment else '#processing-instruction'
        tags[name] += 1
        if name == 'region':
            volume += _volume((_read_position(node, _FROM), _read_position(node, _TO)))
    return dict(elementsByTag=dict(sorted(tags.items())),
                entities=tags['monster'] + tags['npc'], spawnGroups=tags['spawn'],
                houses=tags['house'], routes=tags['route'], waypoints=tags['waypoint'],
                regions=tags['region'], regionCellsInclusive=volume,
                apng=tags['apng'], soundSources=tags['soundsrc'], comments=tags['#comment'])


def _identity_digest(root: ET.Element) -> str:
    records = []
    for node, path in _walk(root):
        if node.tag in {'spawn', 'region'}:
            continue  # Structural nodes may split; each clone keeps its attributes.
        coordinates = _allowed_coordinates(path) - {'offsetX', 'offsetY'}
        records.append((node.tag, [(k, v) for k, v in node.attrib.items() if k not in coordinates]))
    return hashlib.sha256(json.dumps(records, ensure_ascii=False).encode('utf-8')).hexdigest()


def _text_signature(document: ET.Element):
    result = []
    for node in document.iter():
        if not isinstance(node.tag, str):
            result.append(('comment' if node.tag is ET.Comment else 'pi', node.text))
        elif node.text and node.text.strip():
            result.append(('text', node.text))
        if node.tail and node.tail.strip():
            result.append(('tail', node.tail))
    return result


def relocate_world_xml(source_path, destination_path,
                       position_mapper: Callable[[Position], Position], *,
                       rectangle_mapper: Callable[[Position, Position], Iterable[Rectangle]] | None = None) -> dict:
    """Write a relocated UTF-8 sidecar exclusively to a previously absent path.

    Returns counts, identity checks and hashes. Invalid/unknown coordinate
    schemas, dropped rectangle cells and mapper failures leave no output file.
    Exact (0,0,0) house exits are the editor's unset-entry sentinel and remain
    unset; zero coordinates in waypoints, APNGs or spawns are legitimate points.
    """
    source = Path(source_path).resolve()
    requested_destination = Path(destination_path)
    if requested_destination.exists() or requested_destination.is_symlink():
        raise FileExistsError(f'O destino precisa ser novo: {requested_destination}')
    destination = requested_destination.resolve()
    if source == destination:
        raise FormatError('Origem e destino não podem ser o mesmo arquivo.')
    raw = source.read_bytes()
    document, root = _parse(raw)
    _check_schema(root)
    before = _counts(document)
    identity_before = _identity_digest(root)
    text_before = _text_signature(document)
    mapped_points = 0
    preserved_placeholders = 0

    def map_point(position):
        nonlocal mapped_points
        result = _position(position_mapper(position), f'position_mapper({position})')
        mapped_points += 1
        return result

    if root.tag == 'spawns':
        replaced = []
        for child in root:
            replaced.extend(_spawn_children(child, map_point) if child.tag == 'spawn' else [child])
        root[:] = replaced
    else:
        # Regions are expanded in place, so records retain their input order.
        for parent, parent_path in list(_walk(root)):
            children = []
            for child in parent:
                path = (*parent_path, child.tag)
                if path == _REGION_PATH:
                    lo, hi = _read_position(child, _FROM), _read_position(child, _TO)
                    if rectangle_mapper is None:
                        rectangles = _map_rectangle_exact(lo, hi, map_point)
                    else:
                        try:
                            rectangles = [_rectangle(r, 'rectangle_mapper') for r in rectangle_mapper(lo, hi)]
                        except TypeError as error:
                            raise FormatError('rectangle_mapper precisa retornar lista de retângulos inclusivos.') from error
                    _validate_rectangles(rectangles, _volume((lo, hi)))
                    for index, (new_lo, new_hi) in enumerate(rectangles):
                        clone = deepcopy(child)
                        _set_position(clone, _FROM, new_lo)
                        _set_position(clone, _TO, new_hi)
                        clone.text = child.text if index == 0 else None
                        clone.tail = child.tail if index == len(rectangles) - 1 else None
                        children.append(clone)
                else:
                    children.append(child)
                    if path == ('houses', 'house'):
                        position = _read_position(child, _ENTRY)
                        if position == (0, 0, 0):
                            preserved_placeholders += 1
                        else:
                            _set_position(child, _ENTRY, map_point(position))
                    elif path in _POINT_PATHS:
                        _set_position(child, _XYZ, map_point(_read_position(child, _XYZ)))
            parent[:] = children

    after = _counts(document)
    identity_after = _identity_digest(root)
    if identity_before != identity_after or text_before != _text_signature(document):
        raise FormatError('Auditoria detectou alteração na ordem, atributos não espaciais, comentários ou textos.')
    for key in ('entities', 'houses', 'routes', 'waypoints', 'regionCellsInclusive', 'apng', 'soundSources', 'comments'):
        if before[key] != after[key]:
            raise FormatError(f'Auditoria detectou perda de conteúdo: {key}.')
    payload = (b'<?xml version="1.0" encoding="utf-8"?>\n'
               + (document.text or '').encode('utf-8')
               + b''.join(ET.tostring(child, encoding='utf-8') for child in document))
    check_document, check_root = _parse(payload)
    if _counts(check_document) != after or _identity_digest(check_root) != identity_after:
        raise FormatError('XML serializado falhou na verificação de releitura.')
    if source.read_bytes() != raw:
        raise FormatError('Origem mudou durante o processamento; nada foi escrito.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids the overwrite race of os.replace/atomic output.
    created = False
    try:
        with destination.open('xb') as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return dict(source=str(source), destination=str(destination), schema=root.tag,
                counts={'before': before, 'after': after}, positionMapperCalls=mapped_points,
                preservedUnsetHouseEntries=preserved_placeholders,
                spawnGroupsAdded=after['spawnGroups'] - before['spawnGroups'],
                regionsAdded=after['regions'] - before['regions'],
                identityOrderSha256Before=identity_before, identityOrderSha256After=identity_after,
                nonSpatialContentPreserved=True,
                sourceSha256=hashlib.sha256(raw).hexdigest(),
                destinationSha256=hashlib.sha256(payload).hexdigest(), sourceUnmodified=True)
