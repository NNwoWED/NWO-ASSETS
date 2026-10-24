from pathlib import Path
import json

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
INCOMING = ROOT / "sprites" / "parede e telhado pra city iwa" / "telhados e varicoes de cor"
REPORT = ROOT / "reports" / "export-iwa-roof-references-11864-11876-20261023.json"
OUT = Path(__file__).resolve().parent


def sheet(entries, destination):
    columns = 4
    cell_w, cell_h = 170, 170
    rows = (len(entries) + columns - 1) // columns
    canvas = Image.new("RGBA", (columns * cell_w, rows * cell_h), (28, 28, 28, 255))
    draw = ImageDraw.Draw(canvas)
    for index, (label, path) in enumerate(entries):
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        sprite = Image.open(path).convert("RGBA").resize((128, 128), Image.Resampling.NEAREST)
        canvas.alpha_composite(sprite, (x + 21, y + 25))
        draw.text((x + 5, y + 5), label, fill=(255, 255, 255, 255))
    canvas.save(destination, format="PNG", optimize=False)


incoming = [(path.name, path) for path in sorted(INCOMING.glob("*.png"))]
exported = json.loads(REPORT.read_text(encoding="utf-8"))["exported"]
references = [(str(entry["requested_id"]), Path(entry["path"])) for entry in exported]
sheet(incoming, OUT / "incoming-roofs.png")
sheet(references, OUT / "reference-roofs-11864-11876.png")
