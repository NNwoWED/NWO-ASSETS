from pathlib import Path
from collections import Counter
import csv,json,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import scan_dat_record_spans,read_dat_animation_timings
from nwoassets.exporter import compose_appearance_sheet
from nwoassets.png import write_png_rgba
from nwoassets.sprites import read_spr_blocks,decode_sprite_rgba
from nwoassets.content import sha256_file

work=ROOT/'work/main-integration-20261117';work.mkdir(exist_ok=True)
source=work/'main-860';source.mkdir(exist_ok=True)
archive=work/'main-860.rar'
sha=json.loads(Path(r'G:\Meu Drive\NEW NWO\logs\main-to-mob-integration-20261117/start.json').read_text('utf8'))['repos']['nwo-otclient-mehah-4.0']['main']
with archive.open('wb')as stream:
 subprocess.run(['git','-C',str(ROOT.parent/'nwo-otclient-mehah-4.0'),'show',sha+':data/things/860.rar'],stdout=stream,check=True)
rar=r'C:\Program Files\WinRAR\Rar.exe'
subprocess.run([rar,'t','-idq',str(archive)],check=True)
subprocess.run([rar,'e','-idq','-o+',str(archive),'860\\Tibia.dat','860\\Tibia.spr','860\\Tibia.otfi','860\\Tibia.glb',str(source)+'\\'],check=True)
otfi=parse_otfi(source/'Tibia.otfi');data=(source/'Tibia.dat').read_bytes()
spans=scan_dat_record_spans(data,otfi,'main DAT')
current=(ROOT/'assets/860/Tibia.dat').read_bytes()
old={(s.category,s.thing_id):s for s in scan_dat_record_spans(current,parse_otfi(ROOT/'assets/860/Tibia.otfi'),'canonical')}
different=[]
for s in spans:
 key=(s.category,s.thing_id)
 if key in old:
  prior=old[key]
  if data[s.start:s.end]!=current[prior.start:prior.end]:different.append(key)
effects=[s for s in spans if s.category=='effects'and 3378<=s.thing_id<=3444]
props=Counter(data[s.start:s.properties_end].hex()for s in effects)
assert props=={'1818001800ff':67},props
timings=read_dat_animation_timings(data,otfi,'effects',{s.thing_id for s in effects},'main DAT')
ids={i for s in effects for a in s.appearances for i in a.sprite_ids if i}
blocks=read_spr_blocks(source/'Tibia.spr',ids,otfi)
pixels={i:decode_sprite_rgba(b,transparency=otfi.transparency)for i,b in blocks.items()};pixels[0]=bytes(4096)
destination=ROOT/'sprites/emojis-main-20261117';destination.mkdir(exist_ok=True)
rows=[]
for index,s in enumerate(effects,1):
 assert len(s.appearances)==1
 app=s.appearances[0]
 assert (app.layers,app.pattern_x,app.pattern_y,app.pattern_z)==(1,1,1,1)
 image=compose_appearance_sheet(app,pixels)
 png=destination/f'effect-{s.thing_id}.png';write_png_rgba(png,image)
 timing=timings.get(s.thing_id)
 if timing:
  assert len(set(timing.durations))==1 and timing.durations[0][0]==timing.durations[0][1]
 duration=timing.durations[0][0] if timing else 100
 rows.append({'sequence':index,'effect_id':s.thing_id,'source_path':str(png),'frames':app.frames,'frame_duration_ms':duration,'animation_async':int(timing.animation_async) if timing else 0,'displacement_x':24,'displacement_y':24})
with(destination/'manifest.csv').open('w',encoding='utf8',newline='')as stream:
 writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
report={'source_commit':sha,'source_archive_sha256':sha256_file(archive),'differing_existing_records':different,'properties':dict(props),'effects':rows,'model_pack':{'path':str(source/'Tibia.glb'),'sha256':sha256_file(source/'Tibia.glb')}}
(ROOT/'reports/main-asset-consolidation-input-20261117.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print('Different existing records',different,flush=True)
print('Effects',len(rows),'frames',dict(Counter(r['frames']for r in rows)),'durations',dict(Counter(r['frame_duration_ms']for r in rows)),flush=True)
