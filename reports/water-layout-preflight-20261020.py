"""Read-only export/import preparation equivalence on all active surface candidates."""
from pathlib import Path
import hashlib
import json
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nwoassets.importer import ManifestEntry, prepare_preserved_appearance
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import scan_dat_record_spans
from nwoassets.sprites import decode_sprite_rgba, read_spr_blocks

paths = {name: ROOT / path for name, path in {
    'dat': 'assets/860/Tibia.dat', 'spr': 'assets/860/Tibia.spr',
    'otb': 'assets/items/items.otb', 'xml': 'assets/items/items.xml',
    'map': 'assets/world/mapanovo.otbm'}.items()}

def hashes():
    result = {}
    for name, path in paths.items():
        with path.open('rb') as stream:
            result[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result

before = hashes()
inventory = json.loads((ROOT / 'reports/water-inventory-20261020.json').read_text(encoding='utf-8'))
assert before == inventory['canonical_hashes'], 'Baseline changed since water inventory; inventory must be renewed'
exported = json.loads((ROOT / 'reports/export-water-layout-preflight-20261020.json').read_text(encoding='utf-8'))
extra = json.loads((ROOT / 'reports/export-water-layout-extra-20261020.json').read_text(encoding='utf-8'))
exported['exported'].extend(extra['exported'])
expected_ids = {a['server_id'] for a in inventory['candidates'] if a['map_occurrences']
                and a['server_id'] not in (20869,20870,15483,20731)}
assert {r['requested_id'] for r in exported['exported']} == expected_ids
assert len(exported['exported']) == len(expected_ids)
data = paths['dat'].read_bytes()
otfi = parse_otfi(ROOT / 'assets/860/Tibia.otfi')
spans = {s.thing_id: s for s in scan_dat_record_spans(data, otfi, str(paths['dat'])) if s.category == 'items'}
ids = {i for record in exported['exported'] for i in spans[record['client_id']].appearances[0].sprite_ids if i}
blocks = read_spr_blocks(paths['spr'], ids, otfi)
pixels = {i: decode_sprite_rgba(block, transparency=otfi.transparency) for i, block in blocks.items()}
pixels[0] = bytes(4096)
with paths['spr'].open('rb') as stream:
    _, sprite_count = struct.unpack('<II', stream.read(8))
records = []
for record in exported['exported']:
    span = spans[record['client_id']]
    appearance = span.appearances[0]
    entry = ManifestEntry(1, record['client_id'], Path(record['path']), 1, None, False, True)
    image, tiles, new_ids, encoded = prepare_preserved_appearance(entry, data, span, otfi, sprite_count + 1)
    assert tiles == tuple(pixels[i] for i in appearance.sprite_ids), record['client_id']
    suffix = len(new_ids) * 4
    assert encoded[:-suffix] == data[span.properties_end:span.end - suffix]
    assert new_ids == tuple(range(sprite_count + 1, sprite_count + 1 + len(tiles)))
    records.append({'server_id': record['requested_id'], 'client_id': record['client_id'],
                    'sheet': [image.width, image.height], 'frames': appearance.frames,
                    'patterns': [appearance.pattern_x, appearance.pattern_y, appearance.pattern_z],
                    'pixels_match_baseline': True, 'appearance_metadata_unchanged': True})
assert hashes() == before
report = {'operation': 'read_only_layout_preflight', 'passed': True, 'canonical_unchanged': True,
          'canonical_hashes': before, 'candidate_count': len(records), 'records': records,
          'official_import_performed': False,
          'pending': 'Palette approval and full appearance review before any recoloring/import/version/sync.'}
(ROOT / 'reports/water-layout-preflight-20261020.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print('WATER_LAYOUT_PREFLIGHT_OK', len(records), 'canonical unchanged')
