from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.otfi import parse_otfi
from nwoassets.properties import read_otb_items
from nwoassets.roundtrip import scan_dat_record_spans


PREPARE = json.loads((ROOT / "reports" / "prepare-lava-recolors-10058-10077-20261023.json").read_text(encoding="utf-8"))
IMPORT = json.loads((ROOT / "reports" / "import-lava-recolors-10058-10077-20261023.json").read_text(encoding="utf-8"))
EXPORT = json.loads((ROOT / "reports" / "export-lava-recolors-10058-10077-20261023.json").read_text(encoding="utf-8"))
DAT_PATH = ROOT / "assets" / "860" / "Tibia.dat"
OTB_PATH = ROOT / "assets" / "items" / "items.otb"
MAP_PATH = ROOT / "assets" / "world" / "mapanovo.otbm"
REPORT_PATH = ROOT / "reports" / "pixel-qa-lava-recolors-10058-10077-20261023.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> None:
    exported = {int(item["requested_id"]): item for item in EXPORT["exported"]}
    dat = DAT_PATH.read_bytes()
    otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
    ids = {
        int(value)
        for item in PREPARE["items"]
        for value in (item["source_client_id"], item["target_client_id"])
    }
    spans = {
        span.thing_id: span
        for span in scan_dat_record_spans(dat, otfi, str(DAT_PATH))
        if span.category == "items" and span.thing_id in ids
    }
    otb = read_otb_items(OTB_PATH)
    checks = []
    for item in PREPARE["items"]:
        source_sid = int(item["source_server_id"])
        source_cid = int(item["source_client_id"])
        target_sid = int(item["target_server_id"])
        target_cid = int(item["target_client_id"])
        intended_path = Path(item["source_path"])
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
        otb_properties_exact = (
            otb[source_sid]["group"] == otb[target_sid]["group"]
            and otb[source_sid]["flags"] == otb[target_sid]["flags"]
            and otb[target_sid]["client_id"] == target_cid
        )
        layout_exact = all(
            int(exported_entry[key]) == expected
            for key, expected in {
                "width": 32,
                "height": 32,
                "layers": 1,
                "pattern_x": 1,
                "pattern_y": 1,
                "pattern_z": 1,
                "frames": 1,
            }.items()
        )
        checks.append(
            {
                "sequence": int(item["sequence"]),
                "collection": item["collection"],
                "source_server_id": source_sid,
                "source_client_id": source_cid,
                "target_server_id": target_sid,
                "target_client_id": target_cid,
                "pixel_exact": pixel_exact,
                "layout_exact": layout_exact,
                "dat_properties_exact": dat_properties_exact,
                "otb_group_and_flags_exact": otb_properties_exact,
                "intended_sha256": sha256(intended_path),
                "exported_sha256": sha256(exported_path),
            }
        )

    backup_hashes = {
        source["path"]: source["sha256"]
        for source in IMPORT["version_backup"]["sources"]
    }
    map_unchanged = sha256(MAP_PATH) == backup_hashes["assets/world/mapanovo.otbm"]
    passed = (
        len(checks) == 80
        and all(
            check[key]
            for check in checks
            for key in ("pixel_exact", "layout_exact", "dat_properties_exact", "otb_group_and_flags_exact")
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
