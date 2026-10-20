"""Deterministic review artifact only; never imports or changes canonical assets."""
from pathlib import Path
import colorsys
import hashlib
import json
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'export/water-review-20261020'
CASES = [(4608, 'blocked', 'server-4608_client-4597.png', 15),
         (4825, 'walkable', 'server-4825_client-4814.png', 15),
         (21112, 'walkable', 'server-21112_client-20227_water.png', 14),
         (25162, 'blocked', 'server-25162_client-24277_water.png', 14)]

def recolor(pixel, kind):
    r, g, b, a = pixel
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    # Retain alpha, neutral foam and pixels outside the blue/green water range.
    if not a or s <= .08 or not 145 <= h * 360 <= 240:
        return pixel
    if kind == 'walkable':
        hue, saturation, value = 178 + (h * 360 - 195) * .15, min(.72, max(.28, s * .75)), .38 + .6 * v
    else:
        hue, saturation, value = 211 + (h * 360 - 195) * .10, max(.5, s * .95), .10 + .6 * v
    rgb = colorsys.hsv_to_rgb(hue / 360, saturation, min(1, value))
    return tuple(round(channel * 255) for channel in rgb) + (a,)

canvas = Image.new('RGB', (730, 820), '#24282e')
draw = ImageDraw.Draw(canvas)
draw.text((20, 12), 'WATER PALETTE PROPOSAL - REVIEW ONLY - no canonical changes', fill='white')
draw.text((20, 34), 'Original', fill='white')
draw.text((370, 34), 'Proposed: turquoise walkable / deep blue blocked', fill='white')
records = []
for index, (sid, kind, filename, frames) in enumerate(CASES):
    path = OUT / filename
    source = Image.open(path).convert('RGBA')
    first = source.crop((0, 0, source.width, source.height // frames))
    proposed = first.copy()
    proposed.putdata([recolor(pixel, kind) for pixel in first.getdata()])
    assert list(first.getchannel('A').getdata()) == list(proposed.getchannel('A').getdata())
    # Repeat exact source pattern grid, then enlarge with nearest neighbour only.
    y = 63 + index * 188
    draw.text((20, y), f'SID {sid} / {kind} / first frame, exact pixels x2', fill='white')
    for x, image in ((20, first), (370, proposed)):
        tiled = Image.new('RGBA', (64, 64))
        for ty in range(0, 64, image.height):
            for tx in range(0, 64, image.width):
                tiled.alpha_composite(image, (tx, ty))
        enlarged = tiled.resize((128, 128), Image.Resampling.NEAREST)
        canvas.paste(enlarged, (x, y + 23), enlarged)
    records.append({'server_id': sid, 'classification': kind, 'source': str(path),
                    'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'preview_frame': 0, 'alpha_preserved': True})
canvas.save(OUT / 'palette-proposal.png')
(ROOT / 'reports/water-palette-preview-20261020.json').write_text(json.dumps({
    'operation': 'review_only', 'approved': False, 'canonical_changed': False,
    'output': str(OUT / 'palette-proposal.png'), 'records': records,
    'method': 'HSV water-color mapping; neutral foam and alpha unchanged; nearest-neighbor display only',
    'excluded_from_surface_proposal': [20869, 20870, 15483, 20731],
    'notes': ['First-frame representative proposal, not an import-ready sheet.',
              'All variants, patterns, frames and shoreline colors need review before import.',
              'Existing import-items does not support multiple patterns; tooling must be extended and tested first.']
}, indent=2) + '\n', encoding='utf-8')
print('WATER_PALETTE_PREVIEW_OK')
