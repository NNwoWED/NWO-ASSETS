"""Read-only canonical house neighborhood for native visual inspection."""
from pathlib import Path
import hashlib,json,mmap,struct,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from nwoassets.map_edit import node_events,tile_record
from nwoassets.properties import read_otb_items,flag_names
path=ROOT/'assets/world/mapanovo.otbm'
def digest():
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
before=digest();mapping=read_otb_items(ROOT/'assets/items/items.otb');tiles=[]
with path.open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as mapped:
    stack=[];area=None
    for opening,offset,payload,_ in node_events(mapped):
        if opening:
            kind=payload[0]
            if kind==4:area=struct.unpack_from('<HHB',payload,1)
            if kind in (5,14) and stack[-1]==4:
                x,y,z=area[0]+payload[1],area[1]+payload[2],area[2]
                if 1232<=x<=1256 and 745<=y<=769 and 4<=z<=7:
                    tile=tile_record(mapped,offset)
                    tiles.append({'position':{'x':x,'y':y,'z':z},'serverIds':tile['items'],
                                  'clientIds':[mapping[sid]['client_id'] for sid in tile['items']],
                                  'otbFlags':[flag_names(mapping[sid]['flags']) for sid in tile['items']],
                                  'houseId':tile['house'],'tileFlags':tile['flags']})
            stack.append(kind)
        elif stack.pop()==4:area=None
assert digest()==before
report={'operation':'read_only_house_corner_native_fixture','canonical_map_hash':before,'map_unchanged':True,
        'reported_position':{'x':1244,'y':757,'z':6},'tiles':tiles}
(ROOT/'reports/house-corner-native-fixture-20261020.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('HOUSE_READ_ONLY_FIXTURE_OK',len(tiles))
for tile in tiles:
    p=tile['position']
    if p['z']==6 and abs(p['x']-1244)<=2 and abs(p['y']-757)<=2:print(json.dumps(tile))
