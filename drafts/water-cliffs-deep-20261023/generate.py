from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
EXPORT_REPORT = ROOT / "reports" / "export-water-cliffs-16421-16445-original-20261023.json"
SOURCE_DIR = ROOT / "export" / "water-cliffs-16421-16445-original-20261023"
OUTPUT_DIR = ROOT / "sprites" / "water-cliffs-deep-20261023"
MANIFEST = OUTPUT_DIR / "water-cliffs-deep-20261023.csv"
TIMING_MANIFEST = OUTPUT_DIR / "water-cliffs-deep-timing-20261023.csv"
REPORT = ROOT / "reports" / "water-cliffs-deep-generation-20261023.json"
PREVIEW = Path(__file__).with_name("preview.png")

# The complete opaque source palette. Semi-transparent edge pixels use the same
# colours with small RGB deviations; they are resolved to the nearest entry and
# retain their original alpha byte.
SOURCE_PALETTE = (
    (7, 80, 115),
    (7, 86, 123),
    (7, 91, 131),
    (8, 100, 133),
    (10, 111, 148),
    (12, 123, 165),
    (15, 147, 191),
    (52, 204, 236),
    (110, 240, 253),
)

# Anchored to the exact deep-water palette of server id 4608. The brighter
# foam entries retain their relative luminance so the original border remains
# legible instead of becoming a flat silhouette.
TARGET_PALETTE = (
    (5, 58, 84),
    (5, 63, 90),
    (5, 66, 96),
    (6, 73, 97),
    (7, 81, 108),
    (9, 90, 120),
    (11, 107, 139),
    (39, 153, 177),
    (89, 193, 204),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def nearest(rgb: tuple[int, int, int]) -> tuple[int, int, int, int]:
    ranked = [
        (sum((rgb[i] - candidate[i]) ** 2 for i in range(3)), index)
        for index, candidate in enumerate(SOURCE_PALETTE)
    ]
    distance_squared, index = min(ranked)
    return index, distance_squared, *TARGET_PALETTE[index]


def main() -> None:
    export = json.loads(EXPORT_REPORT.read_text(encoding="utf-8-sig"))
    entries = export["exported"]
    requested = list(range(16421, 16446))
    assert export["passed"] is True
    assert [int(entry["requested_id"]) for entry in entries] == requested
    assert len(entries) == 25

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated: list[dict] = []
    manifest_rows: list[dict] = []
    preview = Image.new("RGBA", (5 * 128, 5 * 128), (30, 30, 30, 255))
    draw = ImageDraw.Draw(preview)

    max_nearest_distance_squared = 0
    alpha_preserved = True
    transparent_preserved = True

    for sequence, entry in enumerate(entries, start=1):
        source_server_id = int(entry["requested_id"])
        source_client_id = int(entry["client_id"])
        source_path = Path(entry["path"])
        assert source_path.parent.resolve() == SOURCE_DIR.resolve()
        assert source_path.exists()
        assert int(entry["frames"]) == 15
        assert int(entry["layers"]) == 1
        assert int(entry["pattern_z"]) == 1

        image = Image.open(source_path).convert("RGBA")
        pixels = list(image.getdata())
        recolored: list[tuple[int, int, int, int]] = []
        mapped_counts = [0] * len(SOURCE_PALETTE)
        for red, green, blue, alpha in pixels:
            if alpha == 0:
                output = (red, green, blue, alpha)
                transparent_preserved &= output == (red, green, blue, alpha)
            else:
                index, distance_squared, target_red, target_green, target_blue = nearest((red, green, blue))
                max_nearest_distance_squared = max(max_nearest_distance_squared, distance_squared)
                assert distance_squared <= 36, (source_server_id, (red, green, blue, alpha), distance_squared)
                mapped_counts[index] += 1
                output = (target_red, target_green, target_blue, alpha)
                alpha_preserved &= output[3] == alpha
            recolored.append(output)

        result = Image.new("RGBA", image.size)
        result.putdata(recolored)
        output_name = f"{sequence:02d}-server-{source_server_id}-deep-water.png"
        output_path = OUTPUT_DIR / output_name
        result.save(output_path, format="PNG", optimize=False, compress_level=9)

        target_server_id = 25639 + sequence
        target_client_id = 24754 + sequence
        duration = 145 if source_server_id <= 16433 else 150
        animation_async = 0 if source_server_id == 16437 else 1
        manifest_rows.append(
            {
                "sequence": sequence,
                "source_server_id": source_server_id,
                "target_server_id": target_server_id,
                "target_client_id": target_client_id,
                "source_path": output_name,
                "frame_width": 32,
                "frame_height": 32,
                "frames": 15,
                "frame_duration_ms": duration,
                "animation_async": animation_async,
                "layers": int(entry["layers"]),
                "pattern_x": int(entry["pattern_x"]),
                "pattern_y": int(entry["pattern_y"]),
                "pattern_z": int(entry["pattern_z"]),
            }
        )
        generated.append(
            {
                "sequence": sequence,
                "source_server_id": source_server_id,
                "source_client_id": source_client_id,
                "target_server_id": target_server_id,
                "target_client_id": target_client_id,
                "source_path": str(source_path),
                "output_path": str(output_path),
                "source_sha256": sha256(source_path),
                "output_sha256": sha256(output_path),
                "size": list(image.size),
                "mapped_pixel_counts": mapped_counts,
                "frame_duration_ms": duration,
                "animation_async": bool(animation_async),
            }
        )

        # Preview only: first 32x32 pattern/frame at 3x nearest-neighbour.
        tile = result.crop((0, 0, 32, 32)).resize((96, 96), Image.Resampling.NEAREST)
        col = (sequence - 1) % 5
        row = (sequence - 1) // 5
        preview.alpha_composite(tile, (col * 128 + 16, row * 128 + 20))
        draw.text((col * 128 + 4, row * 128 + 3), f"{source_server_id}>{target_server_id}", fill=(255, 255, 255, 255))

    fields = [
        "sequence",
        "source_server_id",
        "target_server_id",
        "target_client_id",
        "source_path",
        "frame_width",
        "frame_height",
        "frames",
        "frame_duration_ms",
        "animation_async",
        "layers",
        "pattern_x",
        "pattern_y",
        "pattern_z",
    ]
    with MANIFEST.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest_rows)

    with TIMING_MANIFEST.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sequence", "category", "client_id", "frame_durations_ms"])
        writer.writeheader()
        writer.writerow(
            {
                "sequence": 1,
                "category": "items",
                "client_id": 24758,
                "frame_durations_ms": "|".join(["145"] * 14 + ["500"]),
            }
        )

    preview.save(PREVIEW, format="PNG", compress_level=9)
    report = {
        "passed": alpha_preserved and transparent_preserved and len(generated) == 25,
        "operation": "deterministic_palette_recolor_for_new_cloned_items",
        "reference_server_id": 4608,
        "source_server_ids": [16421, 16445],
        "target_server_ids": [25640, 25664],
        "target_client_ids": [24755, 24779],
        "source_palette": SOURCE_PALETTE,
        "target_palette": TARGET_PALETTE,
        "max_nearest_rgb_distance_squared": max_nearest_distance_squared,
        "alpha_preserved": alpha_preserved,
        "transparent_pixels_preserved": transparent_preserved,
        "resampling": "none",
        "ai_generation": False,
        "manifest": str(MANIFEST),
        "timing_manifest": str(TIMING_MANIFEST),
        "preview": str(PREVIEW),
        "generated": generated,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "generated": len(generated), "manifest": str(MANIFEST), "report": str(REPORT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
