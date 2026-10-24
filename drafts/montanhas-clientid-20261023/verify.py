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
from nwoassets.roundtrip import scan_dat_record_spans


PREPARE = json.loads((ROOT / "reports" / "prepare-montanhas-recolors-clientid-20261023.json").read_text(encoding="utf-8"))
IMPORT = json.loads((ROOT / "reports" / "import-montanhas-recolors-clientid-20261023.json").read_text(encoding="utf-8"))
EXPORT = json.loads((ROOT / "reports" / "export-montanhas-recolors-clientid-20261023.json").read_text(encoding="utf-8"))
DAT_PATH = ROOT / "assets" / "860" / "Tibia.dat"
OTB_PATH = ROOT / "assets" / "items" / "items.otb"
MAP_PATH = ROOT / "assets" / "world" / "mapanovo.otbm"
REPORT_PATH = ROOT / "reports" / "pixel-qa-montanhas-recolors-clientid-20261023.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> None:
    exported = {int(item["requested_id"]): item for item in EXPORT["exported"]}
    dat = DAT_PATH.read_bytes()
    otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
    client_ids = {
        int(value)
        for item in PREPARE["items"]
        for value in (item["source_client_id"], item["target_client_id"])
    }
    spans = {
        span.thing_id: span
        for span in scan_dat_record_spans(dat, otfi, str(DAT_PATH))
        if span.category == "items" and span.thing_id in client_ids
    }
    otb = read_otb_items(OTB_PATH)
    checks = []
    for item in PREPARE["items"]:
        source_sid = int(item["source_server_id"])
        source_cid = int(item["source_client_id"])
        target_sid = int(item["target_server_id"])
        target_cid = int(item["target_client_id"])
        intended_path = Path(item["normalized_path"])
        exported_entry = exported[target_sid]
        exported_path = Path(exported_entry["path"])
        with Image.open(intended_path) as intended_source, Image.open(exported_path) as actual_source:
            intended = intended_source.convert("RGBA")
            actual = actual_source.convert("RGBA")
            pixel_exact = intended.size == actual.size and intended.tobytes() == actual.tobytes()
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
        layout = item["layout"]
        canonical_width, canonical_height = item["canonical_size"]
        layout_exact = (
            int(exported_entry["width"]) == int(canonical_width)
            and int(exported_entry["height"]) == int(canonical_height)
            and all(
                int(exported_entry[key]) == int(layout[key])
                for key in ("layers", "pattern_x", "pattern_y", "pattern_z", "frames")
            )
        )
        checks.append(
            {
                "sequence": int(item["sequence"]),
                "collection": item["collection"],
                "filename": item["filename"],
                "named_reference_id": int(item["named_reference_id"]),
                "source_server_id": source_sid,
                "source_client_id": source_cid,
                "target_server_id": target_sid,
                "target_client_id": target_cid,
                "pixel_exact": pixel_exact,
                "layout_exact": layout_exact,
                "dat_properties_exact": dat_properties_exact,
                "otb_group_and_flags_exact": otb_properties_exact,
                "normalized_sha256": sha256(intended_path),
                "exported_sha256": sha256(exported_path),
            }
        )

    backup_hashes = {
        source["path"]: source["sha256"]
        for source in IMPORT["version_backup"]["sources"]
    }
    map_unchanged = sha256(MAP_PATH) == backup_hashes["assets/world/mapanovo.otbm"]
    boolean_keys = ("pixel_exact", "layout_exact", "dat_properties_exact", "otb_group_and_flags_exact")
    passed = (
        len(checks) == 924
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
        "alpha_group_set_exact_count": sum(item["alpha_group_set_exact"] for item in PREPARE["items"]),
        "patterns_reordered_count": sum(item["groups_reordered_to_reference"] for item in PREPARE["items"]),
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
