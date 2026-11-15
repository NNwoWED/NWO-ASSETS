"""Piecewise, audited translations used by new-world composition.

Ownership is column based: every floor in one source block follows the same
translation. Rectangular area metadata is split exactly at ownership boundaries.
"""
from collections import deque
import json
from pathlib import Path

from .map_edit import MapEditError, _position


class PlacementMap:
    def __init__(self, manifest):
        if isinstance(manifest, (str, Path)):
            manifest = json.loads(Path(manifest).read_text(encoding='utf-8'))
        self.manifest = manifest
        self.size = manifest['blockSize']
        self.transforms = {p['id']: tuple(p['translation']) for p in manifest['placements']}
        self.owners = {}
        for by, left, right, owner in manifest['ownershipRows']:
            if owner not in self.transforms: raise MapEditError('Unidade sem destino.')
            for bx in range(left, right+1):
                if (bx, by) in self.owners: raise MapEditError('Unidades de origem sobrepostas.')
                self.owners[bx, by] = owner
        if not self.owners: raise MapEditError('Plano vazio.')
        self.explicit = frozenset(self.owners)
        self.fallbacks = {}

    def owner(self, x, y):
        key = (x//self.size, y//self.size)
        if key in self.owners: return self.owners[key]
        if key not in self.fallbacks:
            # Stable nearest ownership for pre-existing empty metadata positions;
            # geometry is never moved to another floor or silently repaired here.
            nearest = min(self.explicit, key=lambda b: ((b[0]-key[0])**2+(b[1]-key[1])**2,b[1],b[0]))
            self.fallbacks[key] = self.owners[nearest]
        return self.fallbacks[key]

    def __call__(self, position):
        x,y,z = _position(position)
        dx,dy,dz = self.transforms[self.owner(x,y)]
        return _position((x+dx,y+dy,z+dz))

    def rectangles(self, lo, hi):
        lo=_position(lo); hi=_position(hi)
        if any(a>b for a,b in zip(lo,hi)): raise MapEditError('Retângulo invertido.')
        step=self.size; horizontal=[]
        for by in range(lo[1]//step, hi[1]//step+1):
            y0=max(lo[1],by*step); y1=min(hi[1],(by+1)*step-1)
            active=None
            for bx in range(lo[0]//step,hi[0]//step+1):
                x0=max(lo[0],bx*step); x1=min(hi[0],(bx+1)*step-1)
                offset=self.transforms[self.owner(x0,y0)]
                if active is not None and active[4]==offset:
                    active[2]=x1
                else:
                    if active is not None: horizontal.append(active)
                    active=[x0,y0,x1,y1,offset]
            if active is not None:horizontal.append(active)
        # Merge vertically adjacent runs with equal translation and X interval.
        pending={}; merged=[]
        for row in horizontal:
            x0,y0,x1,y1,offset=row; key=(x0,x1,offset)
            old=pending.get(key)
            if old is not None and old[3]+1==y0:old[3]=y1
            else:
                if old is not None:merged.append(old)
                pending[key]=row
        merged.extend(pending.values())
        result=[]
        for x0,y0,x1,y1,(dx,dy,dz) in merged:
            result.append((_position((x0+dx,y0+dy,lo[2]+dz)),_position((x1+dx,y1+dy,hi[2]+dz))))
        return sorted(result)
