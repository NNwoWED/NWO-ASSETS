from __future__ import annotations

import csv
from collections import Counter, defaultdict, deque
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.appearance_sheet import split_appearance_sheet, split_flattened_z_sheet
from nwoassets.exporter import compose_appearance_sheet
from nwoassets.otfi import parse_otfi
from nwoassets.png import normalize_rgba, read_png_rgba, write_png_rgba
from nwoassets.properties import read_otb_items
from nwoassets.roundtrip import DatAppearance, scan_dat_record_spans


SOURCE_ROOT = ROOT / "sprites" / "montanhas"
BASE_MANIFEST = ROOT / "importados" / "montanha-20260928" / "import-montanha-20260928.csv"
REFERENCE_REPORT = ROOT / "reports" / "export-montanhas-reference-25408-25561-20261023.json"
MANIFEST = SOURCE_ROOT / "montanhas-recolors-clientid-20261023.csv"
REPORT = ROOT / "reports" / "prepare-montanhas-recolors-clientid-20261023.json"
NORMALIZED_ROOT = SOURCE_ROOT / "_normalized_20261023"
COLLECTIONS = (
    "01_arenito_dourado",
    "02_areia_palha",
    "03_ocre_queimado",
    "04_terracota",
    "05_oliva_seco",
    "06_cinza_quente",
)
FIRST_TARGET_SERVER_ID = 25873
FIRST_TARGET_CLIENT_ID = 24988


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


def read_base_rows() -> list[dict[str, str]]:
    with BASE_MANIFEST.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 154
    assert [int(row["sequence"]) for row in rows] == list(range(1, 155))
    assert [int(row["target_server_id"]) for row in rows] == list(range(25408, 25562))
    assert [int(row["target_client_id"]) for row in rows] == list(range(24523, 24677))
    assert len({Path(row["source_path"]).name for row in rows}) == 154
    return rows


def main() -> None:
    base_rows = read_base_rows()
    reference_report = json.loads(REFERENCE_REPORT.read_text(encoding="utf-8-sig"))
    references = {int(item["requested_id"]): item for item in reference_report["exported"]}
    assert set(references) == set(range(25408, 25562))

    otb = read_otb_items(ROOT / "assets" / "items" / "items.otb")
    max_server_id = max(otb)
    assert max_server_id == FIRST_TARGET_SERVER_ID - 1, (max_server_id, FIRST_TARGET_SERVER_ID - 1)
    dat_path = ROOT / "assets" / "860" / "Tibia.dat"
    otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
    item_spans = [span for span in scan_dat_record_spans(dat_path.read_bytes(), otfi, str(dat_path)) if span.category == "items"]
    max_client_id = max(span.thing_id for span in item_spans)
    assert max_client_id == FIRST_TARGET_CLIENT_ID - 1, (max_client_id, FIRST_TARGET_CLIENT_ID - 1)

    expected_names = {Path(row["source_path"]).name for row in base_rows}
    rows: list[dict[str, object]] = []
    audited: list[dict[str, object]] = []
    sequence = 0
    for collection in COLLECTIONS:
        folder = SOURCE_ROOT / collection
        assert folder.is_dir(), folder
        actual_names = {path.name for path in folder.glob("*.png")}
        assert actual_names == expected_names, (collection, sorted(actual_names ^ expected_names))
        for base in base_rows:
            filename = Path(base["source_path"]).name
            named_reference_id = int(base["source_server_id"])
            source_server_id = int(base["target_server_id"])
            source_client_id = int(base["target_client_id"])
            reference = references[source_server_id]
            assert int(reference["client_id"]) == source_client_id
            assert otb[source_server_id]["client_id"] == source_client_id

            path = folder / filename
            header = png_header(path)
            assert header["bit_depth"] == 8 and header["color_type"] == 6
            assert header["compression"] == 0 and header["filter"] == 0 and header["interlace"] == 0
            layers = int(reference["layers"])
            pattern_x = int(reference["pattern_x"])
            pattern_y = int(reference["pattern_y"])
            pattern_z = int(reference["pattern_z"])
            frames = int(reference["frames"])
            canonical_size = (int(reference["width"]), int(reference["height"]))
            frame_width = canonical_size[0] // (layers * pattern_x)
            frame_height = canonical_size[1] // (frames * pattern_y * pattern_z)
            assert frame_width % 32 == 0 and frame_height % 32 == 0
            width_cells = frame_width // 32
            height_cells = frame_height // 32
            flattened_size = (
                frame_width * layers * pattern_x * pattern_z,
                frame_height * pattern_y * frames,
            )
            assert (header["width"], header["height"]) == flattened_size, (
                path,
                header,
                flattened_size,
            )

            image = normalize_rgba(read_png_rgba(
                path,
                max_width=header["width"],
                max_height=header["height"],
            ))
            reference_path = Path(reference["path"])
            reference_image = normalize_rgba(read_png_rgba(
                reference_path,
                max_width=canonical_size[0],
                max_height=canonical_size[1],
            ))
            groups = split_flattened_z_sheet(
                image,
                sprite_size=32,
                width=width_cells,
                height=height_cells,
                layers=layers,
                pattern_x=pattern_x,
                pattern_y=pattern_y,
                pattern_z=pattern_z,
                frames=frames,
            )
            reference_groups = split_appearance_sheet(
                reference_image,
                sprite_size=32,
                width=width_cells,
                height=height_cells,
                layers=layers,
                pattern_x=pattern_x,
                pattern_y=pattern_y,
                pattern_z=pattern_z,
                frames=frames,
            )

            def alpha_key(group: tuple[bytes, ...]) -> tuple[bytes, ...]:
                return tuple(tile[3::4] for tile in group)

            reference_keys = tuple(alpha_key(group) for group in reference_groups)
            new_keys = tuple(alpha_key(group) for group in groups)
            alpha_group_set_exact = Counter(reference_keys) == Counter(new_keys)
            if alpha_group_set_exact:
                by_key: dict[tuple[bytes, ...], deque[tuple[bytes, ...]]] = defaultdict(deque)
                for key, group in zip(new_keys, groups):
                    by_key[key].append(group)
                ordered_groups = tuple(by_key[key].popleft() for key in reference_keys)
            elif len(groups) == 1:
                ordered_groups = groups
            else:
                raise AssertionError(
                    f"{path}: máscaras alpha não preservam os patterns da referência {source_server_id}"
                )
            groups_reordered = ordered_groups != groups
            ordered_tiles = tuple(tile for group in ordered_groups for tile in group)
            synthetic_ids = tuple(range(1, len(ordered_tiles) + 1))
            appearance = DatAppearance(
                width_cells,
                height_cells,
                None,
                layers,
                pattern_x,
                pattern_y,
                pattern_z,
                frames,
                synthetic_ids,
            )
            normalized = compose_appearance_sheet(
                appearance,
                dict(zip(synthetic_ids, ordered_tiles)),
                sprite_size=32,
            )
            assert (normalized.width, normalized.height) == canonical_size
            normalized_path = NORMALIZED_ROOT / collection / filename
            normalized_path.parent.mkdir(parents=True, exist_ok=True)
            write_png_rgba(normalized_path, normalized)

            sequence += 1
            target_server_id = FIRST_TARGET_SERVER_ID + sequence - 1
            target_client_id = FIRST_TARGET_CLIENT_ID + sequence - 1
            rows.append(
                {
                    "sequence": sequence,
                    "source_server_id": source_server_id,
                    "target_server_id": target_server_id,
                    "target_client_id": target_client_id,
                    "source_path": f"_normalized_20261023/{collection}/{filename}",
                    "frame_width": frame_width,
                    "frame_height": frame_height,
                    "frames": frames,
                    "frame_duration_ms": "",
                    "animation_async": "",
                    "layers": layers,
                    "pattern_x": pattern_x,
                    "pattern_y": pattern_y,
                    "pattern_z": pattern_z,
                }
            )
            audited.append(
                {
                    "sequence": sequence,
                    "collection": collection,
                    "filename": filename,
                    "named_reference_id": named_reference_id,
                    "source_server_id": source_server_id,
                    "source_client_id": source_client_id,
                    "target_server_id": target_server_id,
                    "target_client_id": target_client_id,
                    "source_path": str(path),
                    "normalized_path": str(normalized_path),
                    "sha256": sha256(path),
                    "normalized_sha256": sha256(normalized_path),
                    "png": header,
                    "canonical_size": list(canonical_size),
                    "alpha_group_set_exact": alpha_group_set_exact,
                    "groups_reordered_to_reference": groups_reordered,
                    "layout": {
                        "layers": layers,
                        "pattern_x": pattern_x,
                        "pattern_y": pattern_y,
                        "pattern_z": pattern_z,
                        "frames": frames,
                        "frame_width": frame_width,
                        "frame_height": frame_height,
                    },
                }
            )

    assert sequence == 924
    with MANIFEST.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    per_collection = len(base_rows)
    collection_ranges = {}
    for index, collection in enumerate(COLLECTIONS):
        offset = index * per_collection
        collection_ranges[collection] = {
            "target_server_ids": [FIRST_TARGET_SERVER_ID + offset, FIRST_TARGET_SERVER_ID + offset + per_collection - 1],
            "target_client_ids": [FIRST_TARGET_CLIENT_ID + offset, FIRST_TARGET_CLIENT_ID + offset + per_collection - 1],
        }
    report = {
        "passed": True,
        "item_count": len(rows),
        "collection_count": len(COLLECTIONS),
        "items_per_collection": per_collection,
        "source_server_ids": [25408, 25561],
        "source_client_ids": [24523, 24676],
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
