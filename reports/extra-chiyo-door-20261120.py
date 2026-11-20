from pathlib import Path
import mmap,struct,json,hashlib,os,zipfile,shutil
from nwoassets.map_edit import node_events,tile_record,rebase_tile,remove_plain_tile_items
from nwoassets.map_publish import publish_map
from nwoassets.runtime_sync import sync_runtime_assets
from nwoassets.versioning import _archive_world
ROOT=Path.cwd();MAP=ROOT/'assets/world/mapanovo.otbm';OFFICIAL=ROOT.parent/'Server-Data-Nwo/data/world/mapanovo.otbm'
def checksum(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
source=checksum(MAP);assert checksum(OFFICIAL)==source=='a8bfc2deb881ed7d4be1ea6b3fb314529cae0e9a338d2ab49a26deed23d14721'
pos=(2754,886,8);area=None;row=None
with MAP.open('rb')as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ)as data:
 for opening,offset,payload,_ in node_events(data):
  if not opening:continue
  if payload[0]==4:area=struct.unpack_from('<HHB',payload,1)
  elif payload[0]in(5,14)and area and (area[0]+payload[1],area[1]+payload[2],area[2])==pos:
   row=tile_record(data,offset);break
assert row and row['items']==[9146,1210]
changed=rebase_tile(remove_plain_tile_items(row['raw'],[1210]),*pos)
(ROOT/'reports/position-before-extra-chiyo-door-20261120.json').write_text(json.dumps({'position':pos,'items':row['items'],'flags':row['flags'],'raw_hex':row['raw'].hex(),'source_sha256':source},indent=2),encoding='utf8')
last=[-1]
def progress(f,msg):
 n=int(f*100)
 if n!=last[0]:print(n,msg,flush=True);last[0]=n
def unchanged(_):assert checksum(OFFICIAL)==source
r=publish_map(ROOT,MAP,{pos:changed},expected_hash=source,source_hash=source,item_removals={pos:[1210]},before_replace=unchanged,progress=progress,journal_path=ROOT/'reports/journal-extra-chiyo-door-20261120.json',journal_context={'operation':'Extra door on mandatory route opens with third puzzle','position':list(pos)})
assert r['passed']and r['committed'];after=checksum(MAP);assert checksum(OFFICIAL)==source
(ROOT/'reports/map-extra-chiyo-door-20261120.json').write_text(json.dumps(r,indent=2),encoding='utf8')
print('Synchronizing extra route door...',flush=True)
s=sync_runtime_assets(ROOT,expected_server_map_hash=source)
assert s['passed']and checksum(OFFICIAL)==after
(ROOT/'reports/sync-runtime-chiyo-final-20261120.json').write_text(json.dumps(s,indent=2),encoding='utf8')
archive=OFFICIAL.with_suffix('.zip');pending=archive.with_name('mapanovo.chiyo-extra-pending.zip');assert not pending.exists()
old_hash=checksum(archive);backup=ROOT/'reports'/('server-map-zip-before-extra-chiyo-'+old_hash+'.zip')
if not backup.exists():shutil.copyfile(archive,backup)
_archive_world(OFFICIAL,pending);assert checksum(archive)==old_hash and checksum(OFFICIAL)==after;os.replace(pending,archive)
with zipfile.ZipFile(archive)as z:
 assert z.namelist()==['mapanovo.otbm']and z.testzip()is None
 with z.open('mapanovo.otbm')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==after
print('Extra door validated and synchronized; official map and server ZIP match.',flush=True)
