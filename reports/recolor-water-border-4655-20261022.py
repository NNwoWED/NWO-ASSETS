"""Reproduce the supplied water palette exactly; no resizing or smoothing."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image
from nwoassets.clone_item_importer import _otb_node_ids
from nwoassets.otb import parse_otb_tree
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import scan_dat_record_spans

root = Path.cwd()
source = root / 'export/water-borders-resume-originals-20261022'
inputs = root / 'sprites/recolor wedson'
report_path = root / 'reports/recolor-water-border-4655-20261022.json'
exports = json.loads((root / 'reports/export-water-borders-resume-originals-20261022.json').read_text(encoding='utf-8'))['exported']
_, otb = parse_otb_tree(root / 'assets/items/items.otb')
links = dict(_otb_node_ids(node, 'recolor-preflight') for node in otb.children)
client_max = max(span.thing_id for span in scan_dat_record_spans(
    (root / 'assets/860/Tibia.dat').read_bytes(),
    parse_otfi(root / 'assets/860/Tibia.otfi'), 'recolor-preflight') if span.category == 'items')
server_max = max(s for s in links if s is not None)
assert len(exports) == 12
for entry in exports:
    assert links[entry['requested_id']] == entry['client_id']

plan = {
    'operation': 'import-cloned-items: twelve new water borders',
    'purpose': 'dark water border variants matching the supplied recolors',
    'card': 'https://trello.com/c/iypxbXLe',
    'baseline_validation': 'reports/validation-water-borders-resume-before-20261022.json',
    'baseline_max_server_id': server_max, 'baseline_max_client_id': client_max,
    'source_server_ids': list(range(4644, 4656)),
    'source_client_ids': [entry['client_id'] for entry in exports],
    'target_server_ids': list(range(server_max + 1, server_max + 13)),
    'target_client_ids': list(range(client_max + 1, client_max + 13)),
    'frame_size': [32, 32], 'frames': 15, 'frame_duration_ms': 100,
    'animation_async': True,
    'policy': 'Clone reference DAT/OTB properties and layer/pattern layout; retain old items and map byte-identically.',
    'generated_source': 'server-4655_client-4644.png from canonical export; exact changed-color lookup from supplied references',
    'input_directory': str(inputs),
}
(root / 'reports/water-borders-final-plan-20261022.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')

# Unchanged observations are not competing recolors: two supplied borders are
# wholly unchanged. Every changed RGB has exactly one destination across all
# eleven references. Require agreement rather than selecting a majority color.
changes = defaultdict(Counter)
reference_hashes = {}
for sid in range(4644, 4655):
    name = f'server-{sid}_client-{sid-11}.png'
    a = Image.open(source / name).convert('RGBA')
    b = Image.open(inputs / name).convert('RGBA')
    assert a.size == b.size
    for old, new in zip(a.get_flattened_data(), b.get_flattened_data()):
        assert old[3] == new[3]
        if old != new:
            changes[old][new] += 1
    reference_hashes[name] = hashlib.sha256((inputs / name).read_bytes()).hexdigest()
assert len(changes) == 77 and all(len(values) == 1 for values in changes.values())
palette = {old: next(iter(values)) for old, values in changes.items()}
name = 'server-4655_client-4644.png'
original_path = inputs / ('original-' + name)
assert not original_path.exists() and not (inputs / name).exists()
original_path.write_bytes((source / name).read_bytes())
im = Image.open(original_path).convert('RGBA')
assert im.size == (32, 480)
before = list(im.get_flattened_data())
stones = {(122, 117, 112, 255), (80, 77, 74, 255), (148, 144, 140, 255),
          (57, 55, 53, 255), (45, 43, 41, 255), (100, 96, 92, 255)}
assert all(pixel in palette or pixel in stones or pixel[3] == 0 for pixel in before)
after = [palette.get(pixel, pixel) for pixel in before]
assert sum(a != b for a, b in zip(before, after)) == 1542
assert all(a == b for a, b in zip(before, after) if a in stones or not a[3])
assert all(a[3] == b[3] for a, b in zip(before, after))
out = Image.new('RGBA', im.size)
out.putdata(after)
out.save(inputs / name, interlace=False)
assert list(Image.open(inputs / name).get_flattened_data()) == after
report = {
    'passed': True, 'method': 'exact, unanimous non-identity palette lookup',
    'operation_plan': plan, 'reference_sha256': reference_hashes,
    'palette': [{'from': old, 'to': new} for old, new in sorted(palette.items())],
    'palette_conflicts': 0, 'changed_pixels': 1542,
    'stone_pixels_preserved': sum(pixel in stones for pixel in before),
    'transparency_preserved': True, 'layout_preserved': True,
    'original_png': str(original_path), 'recolor_png': str(inputs / name),
    'original_sha256': hashlib.sha256(original_path.read_bytes()).hexdigest(),
    'recolor_sha256': hashlib.sha256((inputs / name).read_bytes()).hexdigest(),
}
report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

fields = ['sequence', 'source_server_id', 'target_server_id', 'target_client_id',
          'source_path', 'frame_width', 'frame_height', 'frames',
          'frame_duration_ms', 'animation_async', 'layers', 'pattern_x', 'pattern_y', 'pattern_z']
with (inputs / 'water-cloned-borders-final-20261022.csv').open('w', encoding='utf-8', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for i, entry in enumerate(exports, 1):
        assert entry['frames'] == 15 and entry['layers'] == 1
        writer.writerow(dict(sequence=i, source_server_id=entry['requested_id'],
            target_server_id=server_max+i, target_client_id=client_max+i,
            source_path=Path(entry['path']).name, frame_width=32, frame_height=32,
            frames=15, frame_duration_ms=100, animation_async=1,
            **{key: entry[key] for key in ('layers', 'pattern_x', 'pattern_y', 'pattern_z')}))
print(json.dumps({'passed': True, 'changed_pixels': 1542,
    'server_range': [server_max+1, server_max+12], 'client_range': [client_max+1, client_max+12]}))
