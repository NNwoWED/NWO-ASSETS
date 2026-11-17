from pathlib import Path
from dataclasses import asdict
import hashlib,json,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nwoassets.roundtrip import scan_dat_record_spans,read_dat_animation_timings
from nwoassets.otfi import parse_otfi
from nwoassets.png import read_png_rgba,normalize_rgba
from nwoassets.sprites import read_spr_blocks,decode_sprite_rgba
from nwoassets.exporter import compose_appearance_sheet
from nwoassets.properties import read_otb_items

source=ROOT/'work/main-integration-20261117/main-860'
data=(ROOT/'assets/860/Tibia.dat').read_bytes()
source_data=(source/'Tibia.dat').read_bytes()
otfi=parse_otfi(ROOT/'assets/860/Tibia.otfi')
source_otfi=parse_otfi(source/'Tibia.otfi')
spans={(s.category,s.thing_id):s for s in scan_dat_record_spans(data,otfi,'canonical')}
old={(s.category,s.thing_id):s for s in scan_dat_record_spans(source_data,source_otfi,'main')}
ids=set(range(3378,3445))
current_times=read_dat_animation_timings(data,otfi,'effects',ids,'canonical')
source_times=read_dat_animation_timings(source_data,source_otfi,'effects',ids,'main')
exports=json.loads((ROOT/'reports/export-main-emojis-20261117.json').read_text('utf8'))['exported']
verified=[]
for exported in exports:
    effect_id=exported['client_id']
    original=normalize_rgba(read_png_rgba(ROOT/f'importados/main-emojis-20261117/effect-{effect_id}.png',max_height=320*48))
    actual=read_png_rgba(Path(exported['path']),max_height=320*48)
    assert original==actual,effect_id
    a=spans['effects',effect_id];b=old['effects',effect_id]
    assert data[a.start:a.properties_end]==source_data[b.start:b.properties_end]
    current_layout=asdict(a.appearances[0]);main_layout=asdict(b.appearances[0])
    current_layout.pop('sprite_ids');main_layout.pop('sprite_ids')
    assert current_layout==main_layout
    for name in ['frames','animation_async','loop_count','start_frame','durations']:
        assert getattr(current_times[effect_id],name)==getattr(source_times[effect_id],name),(effect_id,name)
    verified.append(effect_id)
retained=json.loads((ROOT/'reports/verification-sprites-batch-20261116.json').read_text('utf8'))['verified']
otb=read_otb_items(ROOT/'assets/items/items.otb')
for row in retained:
    row['dat_id']=int(otb[row['id']]['client_id']) if row['category']=='items' else row['id']
sprite_ids={i for row in retained for app in spans[row['category'],row['dat_id']].appearances for i in app.sprite_ids if i}
blocks=read_spr_blocks(ROOT/'assets/860/Tibia.spr',sprite_ids,otfi)
pixels={i:decode_sprite_rgba(value,transparency=otfi.transparency)for i,value in blocks.items()};pixels[0]=bytes(4096)
for row in retained:
    rgba=b''.join(compose_appearance_sheet(app,pixels).rgba for app in spans[row['category'],row['dat_id']].appearances)
    assert hashlib.sha256(rgba).hexdigest()==row['pixels_sha256']
sync=json.loads((ROOT/'reports/sync-runtime-main-integration-final-20261117.json').read_text('utf8'))
assert sync['passed']
report={'passed':True,'emoji_effects':verified,'pixels_layout_properties_timings_equal_main':True,'previous_materials_and_outfits_verified':len(retained),'sync_passed':True}
(ROOT/'reports/verification-main-consolidation-20261117.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print('Verified 67 effects including loop metadata, retained 17 previous appearances and runtime synchronization')
