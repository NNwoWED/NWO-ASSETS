"""Match the added water borders without changing geometry or animation."""
from collections import Counter
import hashlib
import json
from math import dist
from pathlib import Path
from statistics import median

from PIL import Image, ImageDraw
from nwoassets.clone_item_importer import _otb_node_ids
from nwoassets.otb import parse_otb_tree
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import read_dat_animation_timings, scan_dat_record_spans

root = Path.cwd()
baseline = json.loads((root / 'reports/validation-water-25606-before-20261022.json').read_text(encoding='utf-8'))
assert baseline['passed'] and not baseline['errors']
exports = json.loads((root / 'reports/export-water-25606-before-20261022.json').read_text(encoding='utf-8'))['exported']
entry = next(e for e in exports if e['requested_id'] == 25606)
assert entry['client_id'] == 24721 and entry['server_ids'] == [25606]
assert (entry['width'], entry['height'], entry['frames'], entry['pattern_y']) == (32, 960, 15, 2)
_, tree = parse_otb_tree(root / 'assets/items/items.otb')
nodes = [n for n in tree.children if _otb_node_ids(n, 'tone-preflight')[1] == 24721]
assert len(nodes) == 1 and _otb_node_ids(nodes[0], 'tone-preflight')[0] == 25606
dat = (root / 'assets/860/Tibia.dat').read_bytes()
otfi = parse_otfi(root / 'assets/860/Tibia.otfi')
span = next(s for s in scan_dat_record_spans(dat, otfi, 'tone-preflight') if s.category == 'items' and s.thing_id == 24721)
timing = read_dat_animation_timings(dat, otfi, 'items', {24721}, 'tone-preflight')[24721]
palette = {tuple(c['from']): tuple(c['to']) for c in json.loads(
    (root / 'reports/recolor-water-border-4655-20261022.json').read_text(encoding='utf-8'))['palette']}
assert len(palette) == 77
work = root / 'sprites/water-25606-tone-20261022'
assert not work.exists()
plan = {
    'operation': 'substituir', 'name': 'Shallow water border',
    'purpose': 'match the tone of the previously added water borders',
    'card': 'https://trello.com/c/iypxbXLe',
    'server_id': 25606, 'client_id': 24721, 'exclusive_otb_link_verified': True,
    'original_export': entry['path'],
    'source_png': str(work / 'server-25606_client-24721.png'),
    'sheet_size': [32, 960], 'frame_size': [32, 32], 'frames': 15,
    'layers': 1, 'pattern_x': 1, 'pattern_y': 2, 'pattern_z': 1,
    'animation_async': timing.animation_async, 'durations': timing.durations,
    'properties_policy': 'Preserve all DAT/OTB properties and full layout/timing; update only target appearance and its SpriteHash.',
    'dat_properties_sha256': hashlib.sha256(dat[span.start:span.properties_end]).hexdigest(),
    'otb_before_hex': nodes[0].data.hex(),
    'map_sha256': hashlib.sha256((root / 'assets/world/mapanovo.otbm').read_bytes()).hexdigest(),
    'palette_reference': 'reports/recolor-water-border-4655-20261022.json',
}
(root / 'reports/water-25606-tone-plan-20261022.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')

work.mkdir()
original = work / 'original-server-25606_client-24721.png'
original.write_bytes(Path(entry['path']).read_bytes())
im = Image.open(original).convert('RGBA')
before = list(im.get_flattened_data())
counts = Counter(before)
stones = {(80, 77, 74, 255), (122, 117, 112, 255), (100, 96, 92, 255),
          (57, 55, 53, 255), (167, 167, 167, 255), (148, 144, 140, 255)}
# Seven pixels have one rare water tone absent from the supplied lookup.
# Estimate its brightness factor from the eight nearest known water colors.
rare = (70, 114, 137, 255)
assert counts[rare] == 7
nearest = sorted(palette.items(), key=lambda pair: (dist(pair[0][:3], rare[:3]), pair[0]))[:8]
factor = median(new[i] / old[i] for old, new in nearest for i in range(3) if old[i])
assert 0.72 < factor < 0.74
rare_target = tuple(round(c * factor) for c in rare[:3]) + (rare[3],)
assert rare_target == (51, 83, 100, 255)
palette[rare] = rare_target
assert all(p[3] == 0 or p in palette or p in stones for p in before)
after = [palette.get(p, p) for p in before]
assert sum(a != b for a, b in zip(before, after)) == 13607
assert all(a == b for a, b in zip(before, after) if not a[3] or a in stones)
assert all(a[3] == b[3] for a, b in zip(before, after))
out = Image.new('RGBA', im.size)
out.putdata(after)
target = work / 'server-25606_client-24721.png'
out.save(target, interlace=False)
assert list(Image.open(target).get_flattened_data()) == after
(work / 'water-25606-tone-20261022.csv').write_text(
    'sequence,client_id,source_path,preserve_layout\n1,24721,server-25606_client-24721.png,1\n', encoding='utf-8')
report = {
    'passed': True, 'changed_pixels': 13607, 'stone_pixels_preserved': sum(counts[s] for s in stones),
    'transparency_preserved': True, 'layout_preserved': True,
    'exact_reference_colors': 77, 'rare_color': {'from': rare, 'to': rare_target,
        'pixels': 7, 'brightness_factor': factor,
        'nearest_reference_pairs': [{'from': a, 'to': b} for a, b in nearest]},
    'original_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
    'recolor_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
    'plan': 'reports/water-25606-tone-plan-20261022.json',
}
(root / 'reports/recolor-water-25606-20261022.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
preview = Image.new('RGBA', (700,320), (35,35,35,255))
draw = ImageDraw.Draw(preview)
reference = Image.open(next(e['path'] for e in exports if e['requested_id'] == 25605)).convert('RGBA')
for i, (label, image) in enumerate([('25606 before', im), ('25606 after', out), ('25605 reference', reference)]):
    draw.text((i*230, 5), label, fill='white')
    preview.alpha_composite(image.crop((0,0,32,64)).resize((128,256), Image.Resampling.NEAREST), (i*230, 30))
preview.convert('RGB').save(root / 'export/water-25606-before-20261022/tone-preview.png')
print(json.dumps({'passed': True, 'changed_pixels': 13607, 'rare_color': rare_target, 'preserved_stone_pixels': report['stone_pixels_preserved']}))
