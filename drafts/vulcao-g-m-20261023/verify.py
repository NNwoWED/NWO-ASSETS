from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.otfi import parse_otfi
from nwoassets.properties import read_otb_items
from nwoassets.roundtrip import read_dat_animation_timings, scan_dat_record_spans


IMPORT = json.loads((ROOT / "reports" / "import-vulcao-g-m-20261023.json").read_text(encoding="utf-8"))
EXPORT = json.loads((ROOT / "reports" / "export-vulcao-g-m-20261023.json").read_text(encoding="utf-8"))
DAT_PATH = ROOT / "assets" / "860" / "Tibia.dat"
OTB_PATH = ROOT / "assets" / "items" / "items.otb"
MAP_PATH = ROOT / "assets" / "world" / "mapanovo.otbm"
REPORT_PATH = ROOT / "reports" / "pixel-qa-vulcao-g-m-20261023.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def timing(value) -> dict[str, object]:
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
    otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
    client_ids = {24684, 24986, 24987}
    spans = {
        span.thing_id: span
        for span in scan_dat_record_spans(dat, otfi, str(DAT_PATH))
        if span.category == "items" and span.thing_id in client_ids
    }
    timings = read_dat_animation_timings(dat, otfi, "items", client_ids, str(DAT_PATH))
    otb = read_otb_items(OTB_PATH)
    expected = (
        (25871, 24986, ROOT / "sprites" / "vulcao-g-m-20261023" / "Vulcao_-_G.png", (96, 960)),
        (25872, 24987, ROOT / "sprites" / "vulcao-g-m-20261023" / "Vulcao_-_M.png", (64, 640)),
    )
    checks = []
    for target_sid, target_cid, intended_path, expected_size in expected:
        exported_entry = exported[target_sid]
        exported_path = Path(exported_entry["path"])
        intended = Image.open(intended_path).convert("RGBA")
        actual = Image.open(exported_path).convert("RGBA")
        source_span = spans[24684]
        target_span = spans[target_cid]
        check = {
            "source_server_id": 25569,
            "source_client_id": 24684,
            "target_server_id": target_sid,
            "target_client_id": target_cid,
            "pixel_exact": intended.size == actual.size and intended.tobytes() == actual.tobytes(),
            "layout_exact": (
                actual.size == expected_size
                and int(exported_entry["layers"]) == 1
                and int(exported_entry["pattern_x"]) == 1
                and int(exported_entry["pattern_y"]) == 1
                and int(exported_entry["pattern_z"]) == 1
                and int(exported_entry["frames"]) == 10
            ),
            "dat_properties_exact": (
                dat[source_span.start : source_span.properties_end]
                == dat[target_span.start : target_span.properties_end]
            ),
            "otb_group_and_flags_exact": (
                otb[25569]["group"] == otb[target_sid]["group"]
                and otb[25569]["flags"] == otb[target_sid]["flags"]
                and otb[target_sid]["client_id"] == target_cid
            ),
            "timing_exact": timing(timings[24684]) == timing(timings[target_cid]),
            "timing": timing(timings[target_cid]),
            "intended_sha256": sha256(intended_path),
            "exported_sha256": sha256(exported_path),
        }
        checks.append(check)

    backup_hashes = {
        source["path"]: source["sha256"]
        for source in IMPORT["version_backup"]["sources"]
    }
    map_unchanged = sha256(MAP_PATH) == backup_hashes["assets/world/mapanovo.otbm"]
    boolean_keys = ("pixel_exact", "layout_exact", "dat_properties_exact", "otb_group_and_flags_exact", "timing_exact")
    passed = (
        len(checks) == 2
        and all(check[key] for check in checks for key in boolean_keys)
        and map_unchanged
        and IMPORT["passed"] is True
        and IMPORT["transaction_committed"] is True
        and IMPORT["final_validation_passed"] is True
    )
    report = {
        "passed": passed,
        "checked_items": len(checks),
        **{f"{key}_count": sum(check[key] for check in checks) for key in boolean_keys},
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
