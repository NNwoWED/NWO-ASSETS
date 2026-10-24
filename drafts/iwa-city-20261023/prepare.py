from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.png import read_png_rgba


SPRITES = ROOT / "sprites"
SOURCE_ROOT = SPRITES / "parede e telhado pra city iwa"
MANIFEST = SPRITES / "import-iwa-city-walls-roofs-20261023.csv"
REPORT = ROOT / "reports" / "prepare-iwa-city-walls-roofs-20261023.json"
START_SERVER_ID = 26827
START_CLIENT_ID = 25942


def ordered_sources() -> list[tuple[str, Path]]:
    base_names = [*(f"{value}.png" for value in range(1, 10)), "20.png", "canto.png",
                  "parede de terra.png", "parede de terra de lado.png", "piru.png"]
    recolor_names = [*(f"{value}.png" for value in range(1, 10)), "20.png", "canto.png",
                     "parede de terra.png", "parede de terra2.png", "piru.png"]
    roof_names = [*(f"{value}.png" for value in range(10, 17)), "piso1.png", "piso2.png"]
    result: list[tuple[str, Path]] = []
    for name in base_names:
        result.append(("00_base", SOURCE_ROOT / name))
    for directory in (
        "01_arenito_dourado", "02_areia_palha", "03_ocre_queimado",
        "04_terracota", "05_oliva_seco", "06_cinza_quente",
    ):
        for name in recolor_names:
            result.append((directory, SOURCE_ROOT / directory / name))
    roof_directory = SOURCE_ROOT / "telhados e varicoes de cor"
    for name in roof_names:
        result.append(("telhados_e_variacoes", roof_directory / name))
    return result


def reference_server_id(path: Path) -> tuple[int, str]:
    name = path.name.casefold()
    if name == "20.png":
        return 25199, "border"
    if name in {"piso1.png", "piso2.png"}:
        return 11864, "roof"
    if path.stem.isdigit():
        number = int(path.stem)
        if 4 <= number <= 16:
            return 11860 + number, "roof"
    return 25565, "wall"


sources = ordered_sources()
actual = {path.resolve() for path in SOURCE_ROOT.rglob("*.png")}
expected = {path.resolve() for _collection, path in sources}
if actual != expected:
    missing = sorted(str(path) for path in expected - actual)
    unexpected = sorted(str(path) for path in actual - expected)
    raise SystemExit(f"inventario divergente; ausentes={missing}; inesperados={unexpected}")
if len(sources) != 107:
    raise SystemExit(f"quantidade inesperada: {len(sources)}")

rows: list[dict[str, object]] = []
counts = {"wall": 0, "roof": 0, "border": 0}
collection_ranges: dict[str, dict[str, int]] = {}
for index, (collection, path) in enumerate(sources):
    image = read_png_rgba(path, max_width=224, max_height=224)
    if image.width % 32 or image.height % 32:
        raise SystemExit(f"dimensao nao multipla de 32: {path} {image.width}x{image.height}")
    source_server_id, category = reference_server_id(path)
    counts[category] += 1
    pattern_x = 3 if (image.width, image.height) == (192, 64) else 1
    frame_width = 64 if pattern_x == 3 else image.width
    target_server_id = START_SERVER_ID + index
    target_client_id = START_CLIENT_ID + index
    relative = path.relative_to(SPRITES).as_posix()
    row = {
        "sequence": index + 1,
        "source_server_id": source_server_id,
        "target_server_id": target_server_id,
        "target_client_id": target_client_id,
        "source_path": relative,
        "frame_width": frame_width,
        "frame_height": image.height,
        "frames": 1,
        "frame_duration_ms": "",
        "animation_async": 0,
        "layers": 1,
        "pattern_x": pattern_x,
        "pattern_y": 1,
        "pattern_z": 1,
        "category": category,
        "collection": collection,
        "source_size": [image.width, image.height],
    }
    rows.append(row)
    block = collection_ranges.setdefault(collection, {
        "server_id_start": target_server_id,
        "server_id_end": target_server_id,
        "client_id_start": target_client_id,
        "client_id_end": target_client_id,
        "count": 0,
    })
    block["server_id_end"] = target_server_id
    block["client_id_end"] = target_client_id
    block["count"] += 1

header = [
    "sequence", "source_server_id", "target_server_id", "target_client_id",
    "source_path", "frame_width", "frame_height", "frames",
    "frame_duration_ms", "animation_async", "layers", "pattern_x",
    "pattern_y", "pattern_z",
]
with MANIFEST.open("w", encoding="utf-8", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

report = {
    "passed": True,
    "item_count": len(rows),
    "target_server_id_range": [rows[0]["target_server_id"], rows[-1]["target_server_id"]],
    "target_client_id_range": [rows[0]["target_client_id"], rows[-1]["target_client_id"]],
    "reference_counts": counts,
    "reference_rules": {
        "wall": 25565,
        "border_named_20_png": 25199,
        "roof_numbered_4_to_16": "11864-11876 (11860 + filename number)",
        "piso1_and_piso2": 11864,
    },
    "pattern_x_3_count": sum(1 for row in rows if row["pattern_x"] == 3),
    "collection_ranges": collection_ranges,
    "manifest": str(MANIFEST),
    "items": rows,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: report[key] for key in (
    "passed", "item_count", "target_server_id_range", "target_client_id_range",
    "reference_counts", "pattern_x_3_count", "collection_ranges",
)}, ensure_ascii=False, indent=2))
