from __future__ import annotations

import json
from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.content import sha256_file
from nwoassets.otfi import parse_otfi
from nwoassets.properties import read_otb_items
from nwoassets.roundtrip import scan_dat_record_spans


PREPARE = ROOT / "reports" / "prepare-iwa-city-walls-roofs-20261023.json"
EXPORT = ROOT / "reports" / "export-iwa-city-walls-roofs-20261023.json"
BEFORE = ROOT / "reports" / "validation-before-iwa-city-walls-roofs-20261023.json"
OUTPUT = ROOT / "reports" / "pixel-properties-qa-iwa-city-walls-roofs-20261023.json"
ARCHIVE = "importados/iwa-city-walls-roofs-20261023/sources"


prepared = json.loads(PREPARE.read_text(encoding="utf-8"))
exported = json.loads(EXPORT.read_text(encoding="utf-8"))
baseline = json.loads(BEFORE.read_text(encoding="utf-8"))
export_by_sid = {entry["requested_id"]: entry for entry in exported["exported"]}

otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
dat_path = ROOT / "assets" / "860" / "Tibia.dat"
dat_data = dat_path.read_bytes()
dat_items = {
    span.thing_id: span
    for span in scan_dat_record_spans(dat_data, otfi, str(dat_path))
    if span.category == "items"
}
otb_items = read_otb_items(ROOT / "assets" / "items" / "items.otb")

baseline_map = next(
    entry for entry in baseline["inventory"]["files"]
    if entry["path"] == "assets/world/mapanovo.otbm"
)
current_map_hash = sha256_file(ROOT / "assets" / "world" / "mapanovo.otbm")

checks = []
for item in prepared["items"]:
    source = ROOT / "sprites" / item["source_path"]
    export = export_by_sid[item["target_server_id"]]
    source_image = Image.open(source).convert("RGBA")
    exported_image = Image.open(export["path"]).convert("RGBA")
    target_node = otb_items[item["target_server_id"]]
    reference_node = otb_items[item["source_server_id"]]
    target_span = dat_items[item["target_client_id"]]
    reference_span = dat_items[reference_node["client_id"]]
    dat_exact = (
        dat_data[target_span.start:target_span.properties_end]
        == dat_data[reference_span.start:reference_span.properties_end]
    )
    otb_exact = (
        target_node["group"] == reference_node["group"]
        and target_node["flags"] == reference_node["flags"]
    )
    layout_exact = (
        export["width"] == source_image.width
        and export["height"] == source_image.height
        and export["layers"] == item["layers"]
        and export["pattern_x"] == item["pattern_x"]
        and export["pattern_y"] == item["pattern_y"]
        and export["pattern_z"] == item["pattern_z"]
        and export["frames"] == item["frames"]
    )
    pixel_exact = (
        source_image.size == exported_image.size
        and source_image.tobytes() == exported_image.tobytes()
    )
    source_relative = Path(item["source_path"]).relative_to("parede e telhado pra city iwa")
    checks.append({
        "sequence": item["sequence"],
        "category": item["category"],
        "collection": item["collection"],
        "source_server_id": item["source_server_id"],
        "target_server_id": item["target_server_id"],
        "target_client_id": item["target_client_id"],
        "archived_source_path": f"{ARCHIVE}/{source_relative.as_posix()}",
        "size": list(source_image.size),
        "pattern_x": item["pattern_x"],
        "pixel_exact": pixel_exact,
        "layout_exact": layout_exact,
        "dat_properties_exact": dat_exact,
        "otb_group_and_flags_exact": otb_exact,
    })

passed = (
    len(checks) == 107
    and all(
        entry["pixel_exact"]
        and entry["layout_exact"]
        and entry["dat_properties_exact"]
        and entry["otb_group_and_flags_exact"]
        for entry in checks
    )
    and current_map_hash == baseline_map["sha256"]
)
report = {
    "passed": passed,
    "checked_items": len(checks),
    "pixel_exact_count": sum(entry["pixel_exact"] for entry in checks),
    "layout_exact_count": sum(entry["layout_exact"] for entry in checks),
    "dat_properties_exact_count": sum(entry["dat_properties_exact"] for entry in checks),
    "otb_group_and_flags_exact_count": sum(entry["otb_group_and_flags_exact"] for entry in checks),
    "category_counts": prepared["reference_counts"],
    "pattern_x_3_count": prepared["pattern_x_3_count"],
    "map_unchanged": current_map_hash == baseline_map["sha256"],
    "map_sha256": current_map_hash,
    "items": checks,
}
OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: report[key] for key in (
    "passed", "checked_items", "pixel_exact_count", "layout_exact_count",
    "dat_properties_exact_count", "otb_group_and_flags_exact_count",
    "category_counts", "pattern_x_3_count", "map_unchanged", "map_sha256",
)}, ensure_ascii=False, indent=2))
if not passed:
    raise SystemExit(1)
