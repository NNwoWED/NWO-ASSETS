from __future__ import annotations

import csv
import hashlib
import json
import struct
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.otfi import parse_otfi
from nwoassets.properties import read_otb_items
from nwoassets.roundtrip import scan_dat_record_spans


SOURCE_ROOT = ROOT / "sprites" / "paredes"
MANIFEST = SOURCE_ROOT / "paredes-recolors-20261023.csv"
REPORT = ROOT / "reports" / "prepare-paredes-recolors-20261023.json"
REFERENCE_REPORT = ROOT / "reports" / "export-paredes-reference-20261023.json"
COLLECTIONS = (
    "00_base_padronizada",
    "01_arenito_dourado",
    "02_areia_palha",
    "03_ocre_queimado",
    "04_terracota",
    "05_oliva_seco",
    "06_cinza_quente",
)
FILE_TO_SERVER_ID = (
    ("item_103_.png", 25575),
    ("item_355_.png", 25576),
    ("item_1038_.png", 25577),
    ("item_1040_.png", 25578),
    ("item_317_.png", 25579),
    ("item_317_2.png", 25580),
    ("item_318_.png", 25581),
    ("item_319_.png", 25582),
    ("item_320_.png", 25583),
    ("item_322_.png", 25584),
    ("item_323_.png", 25585),
    ("item_756_.png", 25586),
    ("item_757_.png", 25587),
    ("item_758_.png", 25588),
    ("item_759_.png", 25589),
    ("item_760_.png", 25590),
    ("2.png", 25598),
    ("toco_1036_.png", 25600),
)
FIRST_TARGET_SERVER_ID = 25745
FIRST_TARGET_CLIENT_ID = 24860


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def png_header(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"PNG inválido: {path}")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", data[16:29]
    )
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "compression": compression,
        "filter": filter_method,
        "interlace": interlace,
    }


def main() -> None:
    reference_report = json.loads(REFERENCE_REPORT.read_text(encoding="utf-8-sig"))
    references = {int(item["requested_id"]): item for item in reference_report["exported"]}
    assert set(references) == {server_id for _, server_id in FILE_TO_SERVER_ID}

    otb = read_otb_items(ROOT / "assets" / "items" / "items.otb")
    max_server_id = max(otb)
    assert max_server_id == FIRST_TARGET_SERVER_ID - 1, (max_server_id, FIRST_TARGET_SERVER_ID - 1)
    dat_path = ROOT / "assets" / "860" / "Tibia.dat"
    otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
    spans = [span for span in scan_dat_record_spans(dat_path.read_bytes(), otfi, str(dat_path)) if span.category == "items"]
    max_client_id = max(span.thing_id for span in spans)
    assert max_client_id == FIRST_TARGET_CLIENT_ID - 1, (max_client_id, FIRST_TARGET_CLIENT_ID - 1)

    rows: list[dict[str, object]] = []
    audited: list[dict[str, object]] = []
    sequence = 0
    for collection in COLLECTIONS:
        folder = SOURCE_ROOT / collection
        assert folder.is_dir(), folder
        actual_names = {path.name for path in folder.glob("*.png")}
        expected_names = {name for name, _ in FILE_TO_SERVER_ID}
        assert actual_names == expected_names, (collection, sorted(actual_names ^ expected_names))
        for filename, source_server_id in FILE_TO_SERVER_ID:
            path = folder / filename
            reference = references[source_server_id]
            source_client_id = int(reference["client_id"])
            assert otb[source_server_id]["client_id"] == source_client_id
            header = png_header(path)
            assert header["bit_depth"] == 8 and header["color_type"] == 6
            assert header["compression"] == 0 and header["filter"] == 0 and header["interlace"] == 0
            expected_size = (int(reference["width"]), int(reference["height"]))
            assert (header["width"], header["height"]) == expected_size, (path, header, expected_size)
            with Image.open(path) as image:
                assert image.mode == "RGBA", (path, image.mode)
                assert image.size == expected_size, (path, image.size, expected_size)
                reference_image = Image.open(reference["path"]).convert("RGBA")
                identical_to_reference = image.convert("RGBA").tobytes() == reference_image.tobytes()

            sequence += 1
            target_server_id = FIRST_TARGET_SERVER_ID + sequence - 1
            target_client_id = FIRST_TARGET_CLIENT_ID + sequence - 1
            rows.append(
                {
                    "sequence": sequence,
                    "source_server_id": source_server_id,
                    "target_server_id": target_server_id,
                    "target_client_id": target_client_id,
                    "source_path": f"{collection}/{filename}",
                    "frame_width": expected_size[0] // int(reference["pattern_x"]),
                    "frame_height": expected_size[1] // int(reference["pattern_y"]),
                    "frames": int(reference["frames"]),
                    "frame_duration_ms": "",
                    "animation_async": "",
                    "layers": int(reference["layers"]),
                    "pattern_x": int(reference["pattern_x"]),
                    "pattern_y": int(reference["pattern_y"]),
                    "pattern_z": int(reference["pattern_z"]),
                }
            )
            audited.append(
                {
                    "sequence": sequence,
                    "collection": collection,
                    "filename": filename,
                    "source_server_id": source_server_id,
                    "source_client_id": source_client_id,
                    "target_server_id": target_server_id,
                    "target_client_id": target_client_id,
                    "source_path": str(path),
                    "sha256": sha256(path),
                    "png": header,
                    "layout": {
                        key: int(reference[key])
                        for key in ("layers", "pattern_x", "pattern_y", "pattern_z", "frames")
                    },
                    "identical_to_reference": identical_to_reference,
                }
            )

    assert sequence == len(COLLECTIONS) * len(FILE_TO_SERVER_ID) == 126
    with MANIFEST.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    collection_ranges = {}
    for index, collection in enumerate(COLLECTIONS):
        offset = index * len(FILE_TO_SERVER_ID)
        collection_ranges[collection] = {
            "target_server_ids": [FIRST_TARGET_SERVER_ID + offset, FIRST_TARGET_SERVER_ID + offset + 17],
            "target_client_ids": [FIRST_TARGET_CLIENT_ID + offset, FIRST_TARGET_CLIENT_ID + offset + 17],
        }
    report = {
        "passed": True,
        "item_count": len(rows),
        "collection_count": len(COLLECTIONS),
        "items_per_collection": len(FILE_TO_SERVER_ID),
        "source_server_ids": [server_id for _, server_id in FILE_TO_SERVER_ID],
        "target_server_ids": [rows[0]["target_server_id"], rows[-1]["target_server_id"]],
        "target_client_ids": [rows[0]["target_client_id"], rows[-1]["target_client_id"]],
        "baseline_max_server_id": max_server_id,
        "baseline_max_client_id": max_client_id,
        "identical_to_reference_count": sum(item["identical_to_reference"] for item in audited),
        "collections": collection_ranges,
        "manifest": str(MANIFEST),
        "items": audited,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
