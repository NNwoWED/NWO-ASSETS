from pathlib import Path
import hashlib,json,mmap,struct
from nwoassets.map_edit import node_events,tile_record,rebase_tile,remove_plain_tile_items
from nwoassets.map_publish import publish_map
ROOT=Path.cwd();MAP=ROOT/'assets/world/mapanovo.otbm';OFFICIAL=ROOT.parent/'Server-Data-Nwo/data/world/mapanovo.otbm'
def checksum(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
source_hash=checksum(MAP)
assert checksum(OFFICIAL)==source_hash=='f4729e973198b4e4e96a923c0515a82d0763f0d8fb67ed8375291c0a2ca95c4f'
points={(2730,866,8),(2726,866,8),(2744,866,8),(2740,866,8),(2754,866,8),(2744,886,8),(2740,886,8),(2730,886,8),(2726,886,8)}
changes={};removals={};before=[];area=None
with MAP.open('rb')as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ)as data:
 for opening,offset,payload,_ in node_events(data):
  if not opening:continue
  if payload[0]==4:area=struct.unpack_from('<HHB',payload,1)
  elif payload[0]in(5,14)and area:
   pos=(area[0]+payload[1],area[1]+payload[2],area[2])
   if pos in points:
    row=tile_record(data,offset);doors=[sid for sid in row['items']if sid in(1209,1210)]
    assert len(doors)==1 and row['items']==[9146,doors[0]],(pos,row['items'])
    raw=remove_plain_tile_items(row['raw'],doors)
    assert tile_record(raw)['items']==[9146] and tile_record(raw)['flags']==row['flags']
    changes[pos]=rebase_tile(raw,*pos);removals[pos]=doors
    before.append({'position':pos,'before':row['items'],'after':[9146],'flags':row['flags'],'before_raw_hex':row['raw'].hex(),'after_raw_hex':raw.hex()})
    if len(changes)==len(points):break
assert set(changes)==points
(ROOT/'reports/chiyo-door-positions-before-20261120.json').write_text(json.dumps({'source_sha256':source_hash,'positions':before},indent=2),encoding='utf8')
def unchanged(_):assert checksum(OFFICIAL)==source_hash,'Official map changed during edit'
last=[-1]
def progress(f,msg):
 percent=int(f*100)
 if last[0]!=percent:print(percent,msg,flush=True);last[0]=percent
r=publish_map(ROOT,MAP,changes,expected_hash=source_hash,source_hash=source_hash,before_replace=unchanged,progress=progress,item_removals=removals,journal_path=ROOT/'reports/journal-chiyo-doors-20261120.json',journal_context={'operation':'Chiyo private runtime doors; remove exactly nine shared gates','official_source':str(OFFICIAL),'official_source_hash':source_hash})
assert r['passed'] and r['committed'] and checksum(OFFICIAL)==source_hash
(ROOT/'reports/map-chiyo-doors-20261120.json').write_text(json.dumps(r,indent=2),encoding='utf8')
print('Map edited, versioned and deeply validated; ready for guarded sync-runtime.',flush=True)
