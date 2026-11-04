from pathlib import Path
import sys,json,hashlib,time
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parents[2]/'NWO-ASSETS';sys.path.insert(0,str(root))
from nwoassets.otbm import inspect_map_position
from nwoassets.map_edit import _mapped,_scan,tile_record,build_tile
from nwoassets.map_publish import publish_map
baseline=json.loads((root/'reports/kiri-hospital-baseline-20261103.json').read_text('utf8'))
assert baseline.get('passed') and not baseline.get('errors'), 'Mandatory baseline validation failed'
region=json.loads((root/'reports/kiri-hospital-region-20261103.json').read_text('utf8'))
targets={(x,y,2) for x in (1801,1802) for y in (1000,1001,1002)}
canonical=root/'assets/world/mapanovo.otbm'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
expected=sha(canonical);assert expected==region['sha256'],'Map changed since region inspection'
unchanged={str(p.relative_to(root)):sha(p) for p in [root/'assets/860/Tibia.dat',root/'assets/860/Tibia.spr',root/'assets/items/items.otb',root/'assets/items/items.xml']}
for pos in sorted(targets):
 report=inspect_map_position(root,*pos)
 assert report['found'] and report['tile_flags']=='0x00000000' and report['house_id'] is None
 assert [(i['server_id'],i['client_id']) for i in report['items']]==[(431,436),(18036,17151)]
 (root/('reports/kiri-pz-before-%s-%s-%s-20261103.json'%pos)).write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
print('Six before reports: flags0, floor SID431/CID436 + carpet SID18036/CID17151; expected canonical hash '+expected,flush=True)
changes={};before_records=[];last=time.monotonic()
def progress(value,message):
 global last
 if time.monotonic()-last>20:
  print(str(round(value*100,1))+'% '+str(message),flush=True);last=time.monotonic()
with _mapped(canonical) as source:
 def collect(pos,begin,end,area):
  if pos not in targets:return
  record=tile_record(source,begin)
  assert not record['protected'],('Unexpected protected attributes',pos,record['protectionReasons'])
  assert record['flags']==0 and record['items']==[431,18036]
  changes[pos]=build_tile(*pos,record['items'],flags=1)
  before_records.append(dict(position=pos,flags=record['flags'],items=record['items'],protectionReasons=record['protectionReasons']))
 _scan(source,on_tile=collect,collect_areas=False,progress=lambda f,*_:progress(f,'Inspecting source tile records'))
assert set(changes)==targets
manifest=dict(operation='Add Protection Zone only',card='https://trello.com/c/ePDtxxsC',canonical=str(canonical),
 expectedMapSha256=expected,positions=before_records,newFlags=1,unchangedAssetHashes=unchanged,
 itemPolicy='No DAT/SPR/OTB/XML properties or appearances change. Same floor/carpet item ordering; simple target tiles have no unknown attributes, nesting or house metadata.')
(root/'reports/kiri-hospital-pz-plan-20261103.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
result=publish_map(root,canonical,changes,expected_hash=expected,source_hash=expected,
 progress=progress,journal_path=root/'reports/kiri-hospital-pz-journal-20261103.json',
 journal_context={'card':manifest['card'],'operation':'Six hospital tile PZ flags','positions':[list(p) for p in sorted(targets)]})
assert result.get('passed') and result.get('committed'),result
for path,value in unchanged.items():assert sha(root/path)==value,'Unrelated canonical asset changed: '+path
(root/'reports/kiri-hospital-pz-result-20261103.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
print(json.dumps(result,ensure_ascii=True),flush=True)
