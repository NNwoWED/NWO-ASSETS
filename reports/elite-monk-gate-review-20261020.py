"""Read-only canonical map triage around the Elite/Kenjin Monk tower."""
from pathlib import Path
import hashlib
import json
import mmap
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nwoassets.map_edit import iter_tile_records, node_events
from nwoassets.otbm import _decode_item_attributes
from nwoassets.properties import read_otb_items, flag_names

paths = {key: ROOT / path for key, path in {
    'dat':'assets/860/Tibia.dat', 'spr':'assets/860/Tibia.spr',
    'otb':'assets/items/items.otb', 'xml':'assets/items/items.xml',
    'map':'assets/world/mapanovo.otbm'}.items()}
def hashes():
    result = {}
    for key,path in paths.items():
        with path.open('rb') as stream:
            result[key] = hashlib.file_digest(stream,'sha256').hexdigest()
    return result
before=hashes()
names={}; candidates=set()
for item in ET.parse(paths['xml']).getroot().iter('item'):
    first=int(item.get('id') or item.get('fromid') or 0)
    last=int(item.get('toid') or first)
    name=item.get('name','')
    is_gate=any(token in name.lower() for token in ('gate','door','fence','portao','port\u00e3o','placa','sign'))
    for sid in range(first,last+1):
        names[sid]=name
        if is_gate: candidates.add(sid)
items=read_otb_items(paths['otb'])
records=[]; count=0
with paths['map'].open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as mapped:
    for tile in iter_tile_records(mapped):
        count+=1
        if 1245<=tile['x']<=1335 and 995<=tile['y']<=1080 and 0<=tile['z']<=7:
            raw_items=[]
            for opening,_,payload,_ in node_events(tile['raw'], start=0):
                if opening and payload[0]==6:
                    sid=int.from_bytes(payload[1:3],'little')
                    attributes=_decode_item_attributes(payload[3:]) if len(payload)>3 else {}
                    if sid in candidates or attributes:
                        otb=items[sid]
                        raw_items.append({'server_id':sid,'client_id':otb['client_id'],'name':names.get(sid,''),
                                          'otb_flags':flag_names(otb['flags']),'attributes':attributes})
            if raw_items:
                records.append({'x':tile['x'],'y':tile['y'],'z':tile['z'],'stack':tile['items'],'objects':raw_items})
        if count%1000000==0: print('ELITE_MONK_SCAN',count,flush=True)
assert hashes()==before
report={'operation':'read_only_elite_monk_gate_triage','canonical_map':str(paths['map']),
        'canonical_unchanged':True,'canonical_hashes':before,'tiles_scanned':count,'records':records,
        'source_region':'Elite Monk/Kenjin Monk/Monk Boss runtime spawn coordinates; expanded tower bounds',
        'official_map_changed':False}
(ROOT/'reports/elite-monk-gate-review-20261020.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('ELITE_MONK_TRIAGE_OK',len(records),'canonical unchanged',flush=True)
for record in records:
    if any('gate' in obj['name'].lower() or obj['attributes'] for obj in record['objects']):
        print(json.dumps(record,ensure_ascii=True),flush=True)
