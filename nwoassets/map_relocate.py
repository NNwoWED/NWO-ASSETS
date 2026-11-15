"""Lossless coordinate relocation for an explicitly requested new-world artifact.

Never publishes a baseline. Item layout follows Src-Nwo/item.cpp and
itemattributes.cpp; an unknown attribute stops relocation instead of guessing.
Only tile offsets and positional references change. All other encoded bytes,
including nested containers, house IDs, flags and action IDs, are retained.
"""
from __future__ import annotations

import struct
from .map_edit import MapEditError, node_events, _escape, _position


FIXED_ITEM_ATTRIBUTES = {
    4:2, 5:2, 8:5, 10:2, 14:1, 15:1, 16:4, 17:1, 18:4,
    20:4, 21:4, 22:2, 23:4, 24:4, 25:4,
    33:4, 34:4, 35:4, 36:4, 37:4, 38:4, 39:4,
    42:1, 43:1, 44:4, 46:4,
}
STRING_ITEM_ATTRIBUTES = {6,7,19,30,31,41,45}


def _require(data, start, size):
    if start < 0 or start+size > len(data): raise MapEditError('Atributo OTBM truncado durante relocação.')
    return start+size


def _string_end(data, start, size=2):
    _require(data,start,size)
    length=int.from_bytes(data[start:start+size],'little')
    return _require(data,start+size,length)


def _attribute_map_end(data,start):
    _require(data,start,2); count=struct.unpack_from('<H',data,start)[0]; cursor=start+2
    for _ in range(count):
        cursor=_string_end(data,cursor)
        _require(data,cursor,1); kind=data[cursor]; cursor+=1
        if kind==1:cursor=_string_end(data,cursor,4)
        elif kind in (2,3):cursor=_require(data,cursor,4)
        elif kind==4:cursor=_require(data,cursor,1)
        else:raise MapEditError(f'Tipo de valor customizado não suportado: {kind}.')
    return cursor


def item_attribute_spans(payload):
    """Yield (kind, value_start, value_end) within a decoded ITEM node header."""
    if len(payload)<3 or payload[0]!=6:raise MapEditError('Cabeçalho de item inválido.')
    cursor=3
    while cursor<len(payload):
        kind=payload[cursor]; cursor+=1; start=cursor
        if kind==0:
            if any(payload[cursor:]):raise MapEditError('Dados não nulos após o fim dos atributos.')
            return
        if kind in FIXED_ITEM_ATTRIBUTES:cursor=_require(payload,cursor,FIXED_ITEM_ATTRIBUTES[kind])
        elif kind in STRING_ITEM_ATTRIBUTES:cursor=_string_end(payload,cursor)
        elif kind==128:cursor=_attribute_map_end(payload,cursor)
        else:raise MapEditError(f'Atributo de item desconhecido na relocação: {kind}.')
        yield kind,start,cursor


def _replace_spans(encoded, replacements):
    """Patch decoded spans while preserving every other original escaped byte."""
    boundaries=[0]; cursor=0
    while cursor<len(encoded):
        cursor+=2 if encoded[cursor]==253 else 1
        if cursor>len(encoded):raise MapEditError('Escape truncado.')
        boundaries.append(cursor)
    parts=[]; previous=0
    for start,end,value in sorted(replacements):
        if not previous<=start<=end<len(boundaries):raise MapEditError('Substituições sobrepostas ou fora do cabeçalho.')
        parts.extend((encoded[boundaries[previous]:boundaries[start]],_escape(value)));previous=end
    parts.append(encoded[boundaries[previous]:])
    return b''.join(parts)


def relocate_tile(raw, destination, position_mapper, *, audit=None):
    """Return relocated tile bytes, mapping teleport destinations recursively.

    position_mapper receives an absolute (x,y,z) tuple and must return a valid
    final position. It may reject unresolved references; no fallback is invented.
    """
    x,y,z=_position(destination); replacements=[]; first=True
    for opening,offset,payload,encoded in node_events(raw,0):
        if not opening:continue
        spans=[]
        if first:
            if payload[0] not in (5,14):raise MapEditError('Relocação requer um nó de tile.')
            spans.append((1,3,bytes((x%256,y%256))));first=False
        elif payload[0]==6:
            for kind,start,end in item_attribute_spans(payload):
                if kind==8:
                    source=struct.unpack_from('<HHB',payload,start)
                    # Existing NWO script teleports use the null destination as
                    # a sentinel. Turning it into a real tile changes gameplay.
                    target=source if source==(0,0,0) else _position(position_mapper(source))
                    if target!=source:spans.append((start,end,struct.pack('<HHB',*target)))
                    if audit is not None:audit.append({'kind':'teleport','source':list(source),'target':list(target)})
        else:
            raise MapEditError(f'Nó filho desconhecido em tile: {payload[0]}.')
        if spans:
            changed=_replace_spans(encoded,spans)
            if changed!=encoded:replacements.append((offset+1,offset+1+len(encoded),changed))
    parts=[]; cursor=0
    for start,end,value in replacements:
        parts.extend((raw[cursor:start],value));cursor=end
    parts.append(raw[cursor:]);return b''.join(parts)


def metadata_position(payload):
    """Return decoded positional offset for TOWN or WAYPOINT; strict lengths."""
    if payload[0]==13:
        _require(payload,0,7); offset=_string_end(payload,5)
    elif payload[0]==16:
        _require(payload,0,3); offset=_string_end(payload,1)
    else:return None
    if _require(payload,offset,5)!=len(payload):raise MapEditError('Town/waypoint contém dados adicionais não reconhecidos.')
    return offset


def relocate_metadata(raw, position_mapper, *, rectangle_mapper=None, audit=None):
    """Relocate towns, waypoints and NWO areas without changing their semantics.

    Area rectangles use inclusive endpoints. A piecewise relocation must supply
    rectangle_mapper(from_xyz,to_xyz), returning disjoint translated rectangles.
    It is responsible for preserving coverage when a source area spans regions.
    """
    replacements=[]
    for opening,offset,payload,encoded in node_events(raw,0):
        if not opening:continue
        kind=payload[0]
        if kind not in (12,13,15,16,17,18,19,20,21,22,23,24):
            raise MapEditError(f'Metadado exige regra explícita de relocação: nó {payload[0]}.')
        if kind==20:
            if len(payload)!=11 or rectangle_mapper is None:
                raise MapEditError('Região de área exige cabeçalho conhecido e mapeamento explícito de retângulos.')
            source_from=struct.unpack_from('<HHB',payload,1);source_to=struct.unpack_from('<HHB',payload,6)
            end=offset+len(encoded)+2
            if raw[end-1:end]!=b'\xff':raise MapEditError('Região de área com filhos inesperados.')
            from .map_edit import _node
            changed=[]
            for lo,hi in rectangle_mapper(source_from,source_to):
                lo=_position(lo);hi=_position(hi)
                if any(a>b for a,b in zip(lo,hi)):raise MapEditError('Retângulo de área invertido.')
                changed.append(_node(bytes((kind,))+struct.pack('<HHBHHB',*lo,*hi)))
            if not changed:raise MapEditError('A relocação não pode descartar uma região de área.')
            replacements.append((offset,end,b''.join(changed)))
            if audit is not None:audit.append({'kind':'areaRegion','source':[source_from,source_to],'parts':len(changed)})
            continue
        position=metadata_position(payload)
        if kind==22:
            if len(payload)!=8:raise MapEditError('Fonte sonora de área inválida.')
            position=1
        elif kind==23:
            position=_string_end(payload,1)
            if _require(payload,position,14)!=len(payload):raise MapEditError('APNG de área inválido.')
        if position is None:continue
        source=struct.unpack_from('<HHB',payload,position); target=_position(position_mapper(source))
        changed=_replace_spans(encoded,[(position,position+5,struct.pack('<HHB',*target))])
        if changed!=encoded:replacements.append((offset+1,offset+1+len(encoded),changed))
        if audit is not None:audit.append({'kind':{13:'town',16:'waypoint',22:'areaSound',23:'areaApng'}[kind],'source':list(source),'target':list(target)})
    parts=[];cursor=0
    for start,end,value in replacements:
        parts.extend((raw[cursor:start],value));cursor=end
    parts.append(raw[cursor:]);return b''.join(parts)
