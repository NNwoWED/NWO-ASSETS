"""Deterministic read-only first-frame illustration from canonical asset exports.

This is an inspection illustration, not an editor or a map publication.
It omits DAT displacement/elevation, live NPCs and lighting.
"""
from pathlib import Path
import json
import sys
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nwoassets.exporter import export_pngs
data=json.loads((ROOT/'reports/ryuji-forge-review-20261020.json').read_text(encoding='utf-8'))
records=[t for t in data['records'] if 1219<=t['position'][0]<=1235 and 760<=t['position'][1]<=773 and t['position'][2]==6]
ids=sorted({sid for t in records for sid in t['stack']} | {20952})
destination=ROOT/'export/ryuji-forge-layout-20261020'
manifest_path=ROOT/'reports/export-ryuji-forge-layout-20261020.json'
if manifest_path.exists():
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
else:
    manifest=export_pngs(ROOT,'items',ids,id_kind='server',output_dir=destination)
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
published='--published' in sys.argv
proposal='--with-bench' in sys.argv or published
if proposal:
    target=next(t for t in records if t['position']==[1223,766,6])
    assert target['stack']==[14931]
    if published:
        persisted=json.loads((ROOT/'reports/position-after-ryuji-bench-20261020.json').read_text(encoding='utf-8'))
        assert persisted['passed'] and persisted['position']=={'x':1223,'y':766,'z':6}
        target['stack']=[item['server_id'] for item in persisted['items']]
        assert target['stack']==[14931,20952] and int(persisted['tile_flags'],16)==1
    else:
        target['stack'].append(20952)
by_id={entry['requested_id']:entry for entry in manifest['exported']}
cache={sid:Image.open(entry['path']).convert('RGBA') for sid,entry in by_id.items()}
canvas=Image.new('RGBA',(17*32,14*32),(25,25,25,255))
def draw_item(sid,x,y):
    entry=by_id[sid];sheet=cache[sid]
    width=entry['width']//(entry['layers']*entry['pattern_x'])
    height=entry['height']//(entry['frames']*entry['pattern_y']*entry['pattern_z'])
    px=x%entry['pattern_x'];py=y%entry['pattern_y']
    for layer in range(entry['layers']):
        sx=(px+layer*entry['pattern_x'])*width;sy=py*height
        appearance=sheet.crop((sx,sy,sx+width,sy+height))
        canvas.alpha_composite(appearance,((x-1219+1)*32-width,(y-760+1)*32-height))
for t in sorted(records,key=lambda t:(t['position'][1],t['position'][0])):
    x,y,z=t['position']
    for sid in t['stack']: draw_item(sid,x,y)
canvas=canvas.resize((canvas.width*2,canvas.height*2),Image.Resampling.NEAREST)
draw=ImageDraw.Draw(canvas)
for x in range(1219,1236):
    cx=(x-1219)*64
    draw.line((cx,0,cx,canvas.height),fill=(255,255,255,35))
    draw.text((cx+3,3),str(x),fill='white',stroke_width=1,stroke_fill='black')
for y in range(760,774):
    cy=(y-760)*64
    draw.line((0,cy,canvas.width,cy),fill=(255,255,255,35))
    draw.text((3,cy+20),str(y),fill='white',stroke_width=1,stroke_fill='black')
x,y=1225,763;cx=(x-1219)*64;cy=(y-760)*64
draw.rectangle((cx+2,cy+2,cx+61,cy+61),outline='yellow',width=3)
draw.text((cx+6,cy+27),'Ryuji',fill='yellow',stroke_width=1,stroke_fill='black')
if proposal:
    cx=(1223-1219)*64;cy=(766-760)*64
    draw.rectangle((cx+2,cy+2,cx+61,cy+61),outline='cyan',width=3)
    draw.text((cx+3,cy+44),'20952',fill='cyan',stroke_width=1,stroke_fill='black')
path=destination/('published-forge-bench.png' if published else ('proposed-forge-bench.png' if proposal else 'canonical-forge-overview.png'))
canvas.save(path)
print('READ_ONLY_PREVIEW',path,'items',len(ids))
