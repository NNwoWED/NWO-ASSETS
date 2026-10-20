"""Read-only canonical tiles for an offline native render at the reported SQM."""
from pathlib import Path
import hashlib,json,mmap,struct,sys
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from nwoassets.map_edit import node_events,tile_record
from nwoassets.properties import read_otb_items
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
                if 1217<=x<=1239 and 1187<=y<=1211 and 4<=z<=7:
                    tile=tile_record(mapped,offset)
                    tiles.append({'position':{'x':x,'y':y,'z':z},'serverIds':tile['items'],
                                  'clientIds':[mapping[sid]['client_id'] for sid in tile['items']],
                                  'tileFlags':tile['flags']})
            stack.append(kind)
        elif stack.pop()==4:area=None
assert digest()==before
spawns=[]
for location in ['NWO-ASSETS/assets/world/mapanovo-spawn.xml','Server-Data-Nwo/data/world/mapanovo-spawn.xml']:
    for spawn in ET.parse(ROOT.parent/location).getroot():
        cx,cy,cz=[int(spawn.get(key,'0')) for key in ['centerx','centery','centerz']]
        if abs(cx-1228)<=8 and abs(cy-1199)<=8:
            for monster in spawn:
                if monster.get('name','').lower()=='gorila':
                    spawns.append({'source':location,'center':[cx,cy,cz],'attributes':monster.attrib})
report={'operation':'read_only_native_gorilla_fixture','canonical_map_hash':before,'map_unchanged':True,
        'reported_position':{'x':1228,'y':1199,'z':6},'outfit':2145,'tiles':tiles,'spawns':spawns}
output=ROOT/'reports/gorilla-native-fixture-20261020.json'
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('GORILLA_READ_ONLY_FIXTURE_OK',len(tiles),'tiles')
for tile in tiles:
    pos=tile['position']
    if pos['z']==6 and (pos['x'],pos['y']) in [(1228,1199),(1230,1197),(1226,1192),(1227,1192),(1226,1202)]:
        print(json.dumps(tile))
