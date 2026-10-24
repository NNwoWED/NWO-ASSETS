from __future__ import annotations

import csv
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.properties import read_otb_items
from nwoassets.roundtrip import scan_dat_record_spans
from nwoassets.otfi import parse_otfi


SOURCE_ROOT = ROOT / "sprites" / "lava"
MANIFEST = SOURCE_ROOT / "lava-recolors-10058-10077-20261023.csv"
REPORT = ROOT / "reports" / "prepare-lava-recolors-10058-10077-20261023.json"
COLLECTIONS = (
    "01_brasas_discretas",
    "02_frestas_laranja",
    "03_lava_intensa",
    "terreno_marrom_com_lava",
)
SOURCE_SERVER_IDS = tuple(range(10058, 10078))
FIRST_TARGET_SERVER_ID = 25665
FIRST_TARGET_CLIENT_ID = 24780
FILENAME_RE = re.compile(r"^server-(\d+)_client-(\d+)_.+\.png$", re.IGNORECASE)


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
    otb = read_otb_items(ROOT / "assets" / "items" / "items.otb")
    max_server_id = max(otb)
    assert max_server_id == FIRST_TARGET_SERVER_ID - 1, (max_server_id, FIRST_TARGET_SERVER_ID - 1)

    dat_path = ROOT / "assets" / "860" / "Tibia.dat"
    otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
    item_spans = [span for span in scan_dat_record_spans(dat_path.read_bytes(), otfi, str(dat_path)) if span.category == "items"]
    max_client_id = max(span.thing_id for span in item_spans)
    assert max_client_id == FIRST_TARGET_CLIENT_ID - 1, (max_client_id, FIRST_TARGET_CLIENT_ID - 1)

    rows: list[dict[str, object]] = []
    audited: list[dict[str, object]] = []
    sequence = 0
    for collection in COLLECTIONS:
        folder = SOURCE_ROOT / collection
        assert folder.is_dir(), folder
        files = sorted(folder.glob("*.png"))
        assert len(files) == 20, (collection, len(files))
        found_server_ids: list[int] = []
        for path in files:
            match = FILENAME_RE.match(path.name)
            assert match, path
            source_server_id = int(match.group(1))
            declared_client_id = int(match.group(2))
            found_server_ids.append(source_server_id)
            assert source_server_id in SOURCE_SERVER_IDS, path
            assert otb[source_server_id]["client_id"] == declared_client_id, (
                path,
                otb[source_server_id]["client_id"],
                declared_client_id,
            )
            header = png_header(path)
            assert header == {
                "width": 32,
                "height": 32,
                "bit_depth": 8,
                "color_type": 6,
                "compression": 0,
                "filter": 0,
                "interlace": 0,
            }, (path, header)
            with Image.open(path) as image:
                assert image.mode == "RGBA", (path, image.mode)
                assert image.size == (32, 32), (path, image.size)

            sequence += 1
            target_server_id = FIRST_TARGET_SERVER_ID + sequence - 1
            target_client_id = FIRST_TARGET_CLIENT_ID + sequence - 1
            rows.append(
                {
                    "sequence": sequence,
                    "source_server_id": source_server_id,
                    "target_server_id": target_server_id,
                    "target_client_id": target_client_id,
                    "source_path": f"{collection}/{path.name}",
                    "frame_width": 32,
                    "frame_height": 32,
                    "frames": 1,
                    "frame_duration_ms": "",
                    "animation_async": "",
                    "layers": 1,
                    "pattern_x": 1,
                    "pattern_y": 1,
                    "pattern_z": 1,
                }
            )
            audited.append(
                {
                    "sequence": sequence,
                    "collection": collection,
                    "source_server_id": source_server_id,
                    "source_client_id": declared_client_id,
                    "target_server_id": target_server_id,
                    "target_client_id": target_client_id,
                    "source_path": str(path),
                    "sha256": sha256(path),
                    "png": header,
                }
            )
        assert sorted(found_server_ids) == list(SOURCE_SERVER_IDS), (collection, found_server_ids)

    assert sequence == 80
    fields = list(rows[0])
    with MANIFEST.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    collection_ranges = {}
    for index, collection in enumerate(COLLECTIONS):
        first = index * 20
        collection_ranges[collection] = {
            "target_server_ids": [FIRST_TARGET_SERVER_ID + first, FIRST_TARGET_SERVER_ID + first + 19],
            "target_client_ids": [FIRST_TARGET_CLIENT_ID + first, FIRST_TARGET_CLIENT_ID + first + 19],
        }
    report = {
        "passed": True,
        "item_count": len(rows),
        "source_server_ids": [SOURCE_SERVER_IDS[0], SOURCE_SERVER_IDS[-1]],
        "target_server_ids": [rows[0]["target_server_id"], rows[-1]["target_server_id"]],
        "target_client_ids": [rows[0]["target_client_id"], rows[-1]["target_client_id"]],
        "baseline_max_server_id": max_server_id,
        "baseline_max_client_id": max_client_id,
        "collections": collection_ranges,
        "manifest": str(MANIFEST),
        "items": audited,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
