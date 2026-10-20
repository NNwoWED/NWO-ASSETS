"""Read-only scan of the authoritative startup Ryuji forge neighborhood."""
from pathlib import Path
import hashlib
import json
import mmap
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nwoassets.map_edit import iter_tile_records, node_events
from nwoassets.otbm import _decode_item_attributes
from nwoassets.properties import read_otb_items, flag_names

paths={key:ROOT/path for key,path in {
    'dat':'assets/860/Tibia.dat','spr':'assets/860/Tibia.spr',
    'otb':'assets/items/items.otb','xml':'assets/items/items.xml',
    'map':'assets/world/mapanovo.otbm'}.items()}
def hashes():
    result={}
    for key,path in paths.items():
        with path.open('rb') as stream: result[key]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result
before=hashes()
names={}
for item in ET.parse(paths['xml']).getroot().iter('item'):
    first=int(item.get('id') or item.get('fromid') or 0)
    last=int(item.get('toid') or first)
    for sid in range(first,last+1): names[sid]=item.get('name','')
items=read_otb_items(paths['otb'])
regions=[{'name':'startup_konoha','center':[1225,763,6]},
         {'name':'spawn_xml_a','center':[1839,1021,6]},
         {'name':'spawn_xml_b','center':[610,975,7]}]
records=[];count=0;bench_positions=[]
with paths['map'].open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as mapped:
    for tile in iter_tile_records(mapped):
        count+=1
        relevant=[region['name'] for region in regions
                  if tile['z']==region['center'][2] and abs(tile['x']-region['center'][0])<=12
                  and abs(tile['y']-region['center'][1])<=12]
        bench=any(sid in (20951,20952) for sid in tile['items'])
        if bench: bench_positions.append({'position':[tile['x'],tile['y'],tile['z']], 'stack':tile['items']})
        if relevant:
            objects=[]
            for opening,_,payload,_ in node_events(tile['raw'],start=0):
                if opening and payload[0]==6:
                    sid=int.from_bytes(payload[1:3],'little');otb=items[sid]
                    objects.append({'server_id':sid,'client_id':otb['client_id'],'name':names.get(sid,''),
                                    'otb_flags':flag_names(otb['flags']),
                                    'attributes':_decode_item_attributes(payload[3:]) if len(payload)>3 else {}})
            records.append({'position':[tile['x'],tile['y'],tile['z']], 'stack':tile['items'],
                            'regions':relevant,'objects':objects})
        if count%1000000==0: print('RYUJI_SCAN',count,flush=True)
assert hashes()==before,'Canonical asset bytes changed during read-only review'
report={'operation':'read_only_ryuji_forge_triage','canonical_unchanged':True,'canonical_hashes':before,
        'canonical_map':str(paths['map']),'tiles_scanned':count,'regions':regions,'records':records,
        'forge_bench_positions':bench_positions,'official_map_changed':False}
(ROOT/'reports/ryuji-forge-review-20261020.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('RYUJI_TRIAGE_OK','region_tiles',len(records),'benches',len(bench_positions),flush=True)
for record in records:
    if any(obj['server_id'] in (20951,20952) or obj['attributes'] for obj in record['objects']):
        print(json.dumps(record,ensure_ascii=True),flush=True)
