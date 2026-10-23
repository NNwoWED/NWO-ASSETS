from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.otfi import parse_otfi
from nwoassets.properties import read_otb_items
from nwoassets.roundtrip import read_dat_animation_timings, scan_dat_record_spans


GENERATION = json.loads((ROOT / "reports" / "water-cliffs-deep-generation-20261023.json").read_text(encoding="utf-8"))
IMPORT = json.loads((ROOT / "reports" / "import-water-cliffs-deep-20261023.json").read_text(encoding="utf-8"))
EXPORT = json.loads((ROOT / "reports" / "export-water-cliffs-deep-20261023.json").read_text(encoding="utf-8"))
DAT_PATH = ROOT / "assets" / "860" / "Tibia.dat"
OTB_PATH = ROOT / "assets" / "items" / "items.otb"
OTFI_PATH = ROOT / "assets" / "860" / "Tibia.otfi"
MAP_PATH = ROOT / "assets" / "world" / "mapanovo.otbm"
REPORT_PATH = ROOT / "reports" / "pixel-qa-water-cliffs-deep-20261023.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def timing_value(value) -> dict:
    return {
        "frames": value.frames,
        "animation_async": value.animation_async,
        "loop_count": value.loop_count,
        "start_frame": value.start_frame,
        "durations": [list(pair) for pair in value.durations],
    }


def main() -> None:
    exported = {int(item["requested_id"]): item for item in EXPORT["exported"]}
    dat = DAT_PATH.read_bytes()
    otfi = parse_otfi(OTFI_PATH)
    source_client_ids = {int(item["source_client_id"]) for item in GENERATION["generated"]}
    target_client_ids = {int(item["target_client_id"]) for item in GENERATION["generated"]}
    spans = {
        span.thing_id: span
        for span in scan_dat_record_spans(dat, otfi, str(DAT_PATH))
        if span.category == "items" and span.thing_id in source_client_ids | target_client_ids
    }
    timings = read_dat_animation_timings(
        dat,
        otfi,
        "items",
        source_client_ids | target_client_ids,
        str(DAT_PATH),
    )
    otb = read_otb_items(OTB_PATH)

    checks = []
    for generated in GENERATION["generated"]:
        source_sid = int(generated["source_server_id"])
        source_cid = int(generated["source_client_id"])
        target_sid = int(generated["target_server_id"])
        target_cid = int(generated["target_client_id"])
        intended_path = Path(generated["output_path"])
        exported_entry = exported[target_sid]
        exported_path = Path(exported_entry["path"])
        intended = Image.open(intended_path).convert("RGBA")
        actual = Image.open(exported_path).convert("RGBA")
        pixel_exact = intended.size == actual.size and ImageChops.difference(intended, actual).getbbox() is None

        source_span = spans[source_cid]
        target_span = spans[target_cid]
        dat_properties_exact = (
            dat[source_span.start : source_span.properties_end]
            == dat[target_span.start : target_span.properties_end]
        )
        source_timing = timing_value(timings[source_cid])
        target_timing = timing_value(timings[target_cid])
        timing_exact = source_timing == target_timing
        otb_properties_exact = (
            otb[source_sid]["group"] == otb[target_sid]["group"]
            and otb[source_sid]["flags"] == otb[target_sid]["flags"]
            and otb[target_sid]["client_id"] == target_cid
        )
        layout_exact = all(
            int(exported_entry[key]) == int(value)
            for key, value in {
                "layers": 1,
                "pattern_x": intended.width // 32,
                "pattern_y": intended.height // (32 * 15),
                "pattern_z": 1,
                "frames": 15,
            }.items()
        )
        checks.append(
            {
                "source_server_id": source_sid,
                "source_client_id": source_cid,
                "target_server_id": target_sid,
                "target_client_id": target_cid,
                "pixel_exact": pixel_exact,
                "layout_exact": layout_exact,
                "dat_properties_exact": dat_properties_exact,
                "otb_group_and_flags_exact": otb_properties_exact,
                "timing_exact": timing_exact,
                "source_timing": source_timing,
                "target_timing": target_timing,
                "intended_sha256": sha256(intended_path),
                "exported_sha256": sha256(exported_path),
            }
        )

    backup_sources = {
        item["path"]: item["sha256"]
        for item in IMPORT["version_backup"]["sources"]
    }
    map_unchanged = sha256(MAP_PATH) == backup_sources["assets/world/mapanovo.otbm"]
    passed = (
        len(checks) == 25
        and all(
            check[key]
            for check in checks
            for key in (
                "pixel_exact",
                "layout_exact",
                "dat_properties_exact",
                "otb_group_and_flags_exact",
                "timing_exact",
            )
        )
        and map_unchanged
        and IMPORT["passed"] is True
        and IMPORT["transaction_committed"] is True
        and IMPORT["final_validation_passed"] is True
    )
    report = {
        "passed": passed,
        "checked_items": len(checks),
        "pixel_exact_count": sum(check["pixel_exact"] for check in checks),
        "layout_exact_count": sum(check["layout_exact"] for check in checks),
        "dat_properties_exact_count": sum(check["dat_properties_exact"] for check in checks),
        "otb_group_and_flags_exact_count": sum(check["otb_group_and_flags_exact"] for check in checks),
        "timing_exact_count": sum(check["timing_exact"] for check in checks),
        "map_unchanged": map_unchanged,
        "map_sha256": sha256(MAP_PATH),
        "checks": checks,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "checks"}, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
