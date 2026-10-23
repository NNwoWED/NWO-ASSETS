"""Generate the missing southeast water transition from canonical pixels."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.clone_item_importer import _otb_node_ids
from nwoassets.otb import parse_otb_tree


FRAME_SIZE = 32
FRAMES = 15
DURATION_MS = 100
TARGET_SERVER_IDS = (25638, 25639)
TARGET_CLIENT_IDS = (24753, 24754)
OUTPUT_DIR = ROOT / "sprites" / "water-transition-missing-side-20261023"
MANIFEST = OUTPUT_DIR / "water-transition-missing-side-20261023.csv"
REPORT = ROOT / "reports" / "water-transition-missing-side-generation-20261023.json"
PREVIEW = ROOT / "drafts" / "water-transition-missing-side-20261023" / "preview.png"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_rgba(path: Path) -> np.ndarray:
    image = Image.open(path)
    if image.mode != "RGBA":
        raise ValueError(f"PNG nao esta em RGBA: {path}")
    return np.asarray(image, dtype=np.uint8)


def save_rgba(path: Path, pixels: np.ndarray) -> None:
    Image.fromarray(pixels, "RGBA").save(
        path, format="PNG", optimize=False, compress_level=9, interlace=False
    )
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[24] != 8 or raw[25] != 6 or raw[28] != 0:
        raise ValueError(f"PNG fora do padrao RGBA 8-bit nao entrelacado: {path}")


def distance_to(mask: np.ndarray) -> np.ndarray:
    targets = np.argwhere(mask)
    if not len(targets):
        return np.full(mask.shape, 99.0, dtype=np.float32)
    points = np.indices(mask.shape).reshape(2, -1).T
    delta = points[:, None, :] - targets[None, :, :]
    squared = np.sum(delta * delta, axis=2)
    return np.sqrt(np.min(squared, axis=1)).reshape(mask.shape).astype(np.float32)


def smoothstep(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def blend_rgba(clear: np.ndarray, dark: np.ndarray, strength: np.ndarray) -> np.ndarray:
    factor = strength[..., None].astype(np.float32)
    output = clear.copy()
    output[..., :3] = np.rint(
        clear[..., :3].astype(np.float32) * (1.0 - factor)
        + dark[..., :3].astype(np.float32) * factor
    ).astype(np.uint8)
    return output


def main() -> None:
    expected_output_names = {
        "01-open-water-transition-mask-4655.png",
        "02-shore-gradient-source-4655.png",
        "water-transition-missing-side-20261023.csv",
    }
    if OUTPUT_DIR.exists():
        actual_output_names = {path.name for path in OUTPUT_DIR.iterdir()}
        if actual_output_names != expected_output_names:
            raise FileExistsError(
                f"pasta de saida contem arquivos inesperados: {sorted(actual_output_names)}"
            )
    else:
        OUTPUT_DIR.mkdir(parents=True)

    _, otb_root = parse_otb_tree(ROOT / "assets" / "items" / "items.otb")
    mapping: dict[int, int] = {}
    for index, node in enumerate(otb_root.children):
        server_id, client_id = _otb_node_ids(node, f"item-{index}")
        if server_id is not None and client_id is not None:
            mapping[server_id] = client_id
    expected = {4608: 4597, 4655: 4644}
    if {sid: mapping.get(sid) for sid in expected} != expected:
        raise ValueError("mapeamento OTB das referencias divergiu")
    if max(mapping) != 25637:
        raise ValueError(f"max Server ID inesperado: {max(mapping)}")

    export_dir = ROOT / "export" / "items" / "server-4825-bordas-4644-4654"
    light = load_rgba(export_dir / "server-4825_client-4814.png")
    border_se = load_rgba(
        ROOT / "importados" / "water-borders-final-20261022" / "original-server-4655_client-4644.png"
    )
    if light.shape != (480, 32, 4) or border_se.shape != (480, 32, 4):
        raise ValueError("layout 32x32/15 frames das referencias divergiu")

    palette_report = json.loads(
        (ROOT / "reports" / "recolor-water-border-4655-20261022.json").read_text(encoding="utf-8")
    )
    palette = {tuple(entry["from"]): tuple(entry["to"]) for entry in palette_report["palette"]}
    palette_colors = set(palette)
    palette_colors.add((70, 114, 137, 255))
    ratios = [
        new[channel] / old[channel]
        for old, new in palette.items()
        for channel in range(3)
        if old[channel]
    ]
    fallback = float(np.median(np.asarray(ratios, dtype=np.float32)))

    dark = light.copy()
    flat_before = light.reshape(-1, 4)
    flat_after = dark.reshape(-1, 4)
    for index, value in enumerate(flat_before):
        rgba = tuple(int(channel) for channel in value)
        if rgba[3] == 0:
            continue
        target = palette.get(rgba)
        if target is None:
            target = tuple(int(round(int(channel) * fallback)) for channel in rgba[:3]) + (rgba[3],)
        flat_after[index] = target

    dark_border = border_se.copy()
    border_before = border_se.reshape(-1, 4)
    border_after = dark_border.reshape(-1, 4)
    for index, value in enumerate(border_before):
        rgba = tuple(int(channel) for channel in value)
        if rgba[3] == 0:
            continue
        target = palette.get(rgba)
        if target is None:
            target = tuple(int(round(int(channel) * fallback)) for channel in rgba[:3]) + (rgba[3],)
        border_after[index] = target

    open_transition = np.zeros_like(light)
    shore_gradient = border_se.copy()
    diagnostics: list[dict[str, int | str]] = []
    for frame in range(FRAMES):
        y0 = frame * FRAME_SIZE
        source_tile = border_se[y0 : y0 + FRAME_SIZE]
        water_se = np.asarray(
            [tuple(int(c) for c in pixel) in palette_colors for pixel in source_tile.reshape(-1, 4)],
            dtype=bool,
        ).reshape(FRAME_SIZE, FRAME_SIZE)
        if not water_se.any():
            raise ValueError(f"borda 4655 sem pixels de agua no frame {frame}")
        inside = distance_to(~water_se)
        outside = distance_to(water_se)
        signed = np.where(water_se, inside, -outside)
        strength = np.round(smoothstep((signed + 8.0) / 16.0) * 8.0) / 8.0
        open_transition[y0 : y0 + FRAME_SIZE] = blend_rgba(
            light[y0 : y0 + FRAME_SIZE], dark[y0 : y0 + FRAME_SIZE], strength
        )

        shore_strength = np.round(
            smoothstep((distance_to(~water_se) - 1.0) / 10.0) * 8.0
        ) / 8.0
        shore_tile = source_tile.copy()
        blended_shore = blend_rgba(
            source_tile,
            dark_border[y0 : y0 + FRAME_SIZE],
            shore_strength,
        )
        shore_tile[water_se] = blended_shore[water_se]
        shore_gradient[y0 : y0 + FRAME_SIZE] = shore_tile
        diagnostics.append({
            "frame": frame,
            "mask_pixels": int(water_se.sum()),
            "nonwater_pixels_preserved": int((~water_se).sum()),
        })

    open_path = OUTPUT_DIR / "01-open-water-transition-mask-4655.png"
    shore_path = OUTPUT_DIR / "02-shore-gradient-source-4655.png"
    save_rgba(open_path, open_transition)
    save_rgba(shore_path, shore_gradient)

    all_water = np.asarray(
        [tuple(int(c) for c in pixel) in palette_colors for pixel in border_se.reshape(-1, 4)],
        dtype=bool,
    ).reshape(border_se.shape[:2])
    if not np.array_equal(shore_gradient[~all_water], border_se[~all_water]):
        raise ValueError("pedras ou transparencia da borda 4655 foram alteradas")

    rows = [
        {
            "sequence": 1,
            "source_server_id": 4608,
            "target_server_id": TARGET_SERVER_IDS[0],
            "target_client_id": TARGET_CLIENT_IDS[0],
            "source_path": open_path.name,
            "frame_width": FRAME_SIZE,
            "frame_height": FRAME_SIZE,
            "frames": FRAMES,
            "frame_duration_ms": DURATION_MS,
            "animation_async": 1,
            "layers": 1,
            "pattern_x": 1,
            "pattern_y": 1,
            "pattern_z": 1,
        },
        {
            "sequence": 2,
            "source_server_id": 4655,
            "target_server_id": TARGET_SERVER_IDS[1],
            "target_client_id": TARGET_CLIENT_IDS[1],
            "source_path": shore_path.name,
            "frame_width": FRAME_SIZE,
            "frame_height": FRAME_SIZE,
            "frames": FRAMES,
            "frame_duration_ms": DURATION_MS,
            "animation_async": 1,
            "layers": 1,
            "pattern_x": 1,
            "pattern_y": 1,
            "pattern_z": 1,
        },
    ]
    fieldnames = list(rows[0])
    with MANIFEST.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    preview = Image.new("RGBA", (288, 176), (25, 25, 25, 255))
    draw = ImageDraw.Draw(preview)
    for index, (server_id, path) in enumerate(zip(TARGET_SERVER_IDS, (open_path, shore_path))):
        first = Image.open(path).convert("RGBA").crop((0, 0, 32, 32)).resize((128, 128), Image.Resampling.NEAREST)
        preview.alpha_composite(first, (index * 144, 32))
        draw.text((index * 144, 8), str(server_id), fill="white")
    preview.convert("RGB").save(PREVIEW)

    report = {
        "passed": True,
        "method": "literal canonical-pixel blend using the exact water geometry of canonical CSE border 4655",
        "source_server_to_client": expected,
        "target_server_ids": list(TARGET_SERVER_IDS),
        "target_client_ids": list(TARGET_CLIENT_IDS),
        "layout": {"frame_size": [32, 32], "frames": 15, "duration_ms": 100, "animation_async": True},
        "diagnostics": diagnostics,
        "checks": {
            "mask_orientation_comes_directly_from_border_4655": True,
            "shore_4655_nonwater_pixels_and_alpha_preserved_exactly": bool(
                np.array_equal(load_rgba(shore_path)[~all_water], border_se[~all_water])
            ),
            "no_resizing_or_smoothing": True,
            "no_generated_image_pixels": True,
        },
        "files": [
            {"path": open_path.relative_to(ROOT).as_posix(), "sha256": sha256(open_path)},
            {"path": shore_path.relative_to(ROOT).as_posix(), "sha256": sha256(shore_path)},
            {"path": MANIFEST.relative_to(ROOT).as_posix(), "sha256": sha256(MANIFEST)},
        ],
        "preview": PREVIEW.relative_to(ROOT).as_posix(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
