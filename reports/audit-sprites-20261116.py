from pathlib import Path
import hashlib
import json
import sys
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import scan_dat_record_spans
from nwoassets.exporter import compose_appearance_sheet
from nwoassets.sprites import read_spr_blocks, decode_sprite_rgba
from nwoassets.properties import read_otb_items
from nwoassets.png import normalize_rgba, PngImage

def pixels(path):
    image = Image.open(path).convert('RGBA')
    normalized = normalize_rgba(PngImage(image.width, image.height, image.tobytes()))
    return image.size, normalized.rgba

def digest(value):
    return hashlib.sha256(value).hexdigest()

otfi = parse_otfi(ROOT/'assets/860/Tibia.otfi')
spans = scan_dat_record_spans((ROOT/'assets/860/Tibia.dat').read_bytes(), otfi, 'canonical DAT')
otb = read_otb_items(ROOT/'assets/items/items.otb')
server_ids = defaultdict(list)
for sid, record in otb.items():
    server_ids[int(record['client_id'])].append(sid)

sources = {}
for path in (ROOT/'sprites').rglob('*.png'):
    size, rgba = pixels(path)
    sources.setdefault(size, []).append((path, rgba, digest(rgba)))

def canvas(appearance):
    return (32*appearance.width*appearance.layers*appearance.pattern_x,
            32*appearance.height*appearance.frames*appearance.pattern_y*appearance.pattern_z)

candidates = []
for span in spans:
    sizes = [canvas(appearance) for appearance in span.appearances]
    if len({size[0] for size in sizes}) != 1:
        continue
    size = (sizes[0][0], sum(value[1] for value in sizes))
    if size in sources:
        candidates.append((span, size))

print('Matching canvas candidates', len(candidates), flush=True)
needed = {sid for span, _ in candidates for app in span.appearances for sid in app.sprite_ids if sid}
blocks = read_spr_blocks(ROOT/'assets/860/Tibia.spr', needed, otfi)
print('Loaded sprite blocks', len(blocks), flush=True)
cache = {0:bytes(4096)}
matches = defaultdict(list)
hashes = {size:{value[2] for value in entries} for size,entries in sources.items()}
for span, size in candidates:
    for app in span.appearances:
        for sid in app.sprite_ids:
            if sid not in cache:
                cache[sid] = decode_sprite_rgba(blocks[sid], transparency=otfi.transparency)
    rgba = b''.join(compose_appearance_sheet(app,cache).rgba for app in span.appearances)
    value = digest(rgba)
    if value in hashes[size]:
        matches[(size,value)].append({'category':span.category,'id':span.thing_id,'server_ids':server_ids.get(span.thing_id,[]) if span.category=='items' else []})

archive = defaultdict(list)
for path in (ROOT/'importados').rglob('*.png'):
    try:
        size, rgba = pixels(path)
    except Exception:
        continue
    if size in sources:
        archive[(size,digest(rgba))].append(str(path.relative_to(ROOT)))

report = []
for size, entries in sources.items():
    for path, rgba, value in entries:
        row = {'path':str(path.relative_to(ROOT)),'size':size,'pixels_sha256':value,
               'canonical_matches':matches[(size,value)],'archived_matches':archive[(size,value)]}
        report.append(row)
        print(json.dumps(row,ensure_ascii=True),flush=True)
(ROOT/'reports/sprites-deduplication-20261116.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
print('Max SID',max(otb),'max CID',max(span.thing_id for span in spans if span.category=='items'),flush=True)
