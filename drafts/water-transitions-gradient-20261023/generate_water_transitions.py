"""Create exact light/dark-water blends without changing the original style."""

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


EXPORT_DIR = ROOT / "export" / "items" / "server-4825-bordas-4644-4654"
DARK_BORDER_DIR = ROOT / "importados" / "water-borders-final-20261022"
OUTPUT_DIR = ROOT / "sprites" / "water-transitions-gradient-20261023"
DRAFT_DIR = ROOT / "drafts" / "water-transitions-gradient-20261023"
PLAN_PATH = ROOT / "reports" / "water-transitions-gradient-plan-20261023.json"
GENERATION_REPORT = (
    ROOT / "reports" / "water-transitions-gradient-generation-20261023.json"
)
MANIFEST_PATH = OUTPUT_DIR / "water-transitions-gradient-20261023.csv"
PALETTE_REPORT = ROOT / "reports" / "recolor-water-border-4655-20261022.json"

FRAME_SIZE = 32
FRAMES = 15
DURATION_MS = 100
BASE_WATER_SERVER_ID = 4825
BASE_WATER_CLIENT_ID = 4814
TARGET_SERVER_START = 25615
TARGET_CLIENT_START = 24730

BORDERS = {
    4644: {"client_id": 4633, "pattern_x": 2, "pattern_y": 1},
    4645: {"client_id": 4634, "pattern_x": 1, "pattern_y": 2},
    4646: {"client_id": 4635, "pattern_x": 2, "pattern_y": 1},
    4647: {"client_id": 4636, "pattern_x": 1, "pattern_y": 2},
    4648: {"client_id": 4637, "pattern_x": 1, "pattern_y": 1},
    4649: {"client_id": 4638, "pattern_x": 1, "pattern_y": 1},
    4650: {"client_id": 4639, "pattern_x": 1, "pattern_y": 1},
    4651: {"client_id": 4640, "pattern_x": 1, "pattern_y": 1},
    4652: {"client_id": 4641, "pattern_x": 1, "pattern_y": 1},
    4653: {"client_id": 4642, "pattern_x": 1, "pattern_y": 1},
    4654: {"client_id": 4643, "pattern_x": 1, "pattern_y": 1},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_rgba(path: Path) -> np.ndarray:
    image = Image.open(path)
    if image.mode != "RGBA":
        raise ValueError(f"PNG nao esta em RGBA: {path}")
    return np.array(image, dtype=np.uint8)


def save_rgba(path: Path, pixels: np.ndarray) -> None:
    Image.fromarray(pixels, "RGBA").save(
        path, format="PNG", optimize=False, compress_level=9, interlace=False
    )
    raw = path.read_bytes()
    if (
        raw[:8] != b"\x89PNG\r\n\x1a\n"
        or raw[24] != 8
        or raw[25] != 6
        or raw[28] != 0
    ):
        raise ValueError(f"PNG fora do padrao RGBA 8-bit nao entrelacado: {path}")


def distance_to(mask: np.ndarray) -> np.ndarray:
    """Exact Euclidean distance from every 32x32 pixel to the closest True pixel."""
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


def quantize_blend(value: np.ndarray) -> np.ndarray:
    """Keep a restrained pixel-art gradient with nine deterministic levels."""
    return np.round(value * 8.0) / 8.0


def blend_rgba(clear: np.ndarray, dark: np.ndarray, strength: np.ndarray) -> np.ndarray:
    factor = strength[..., None].astype(np.float32)
    rgb = np.rint(
        clear[..., :3].astype(np.float32) * (1.0 - factor)
        + dark[..., :3].astype(np.float32) * factor
    ).astype(np.uint8)
    output = clear.copy()
    output[..., :3] = rgb
    return output


def find_export(server_id: int, client_id: int) -> Path:
    matches = list(EXPORT_DIR.glob(f"server-{server_id}_client-{client_id}.png"))
    if len(matches) != 1:
        raise ValueError(
            f"exportacao canonica ambigua/ausente para SID {server_id} CID {client_id}"
        )
    return matches[0]


def find_dark_border(server_id: int, client_id: int) -> Path:
    matches = list(DARK_BORDER_DIR.glob(f"server-{server_id}_client-{client_id}.png"))
    if len(matches) != 1:
        raise ValueError(
            f"borda escura ambigua/ausente para SID {server_id} CID {client_id}"
        )
    return matches[0]


def verify_otb_mapping() -> dict[int, int]:
    _, root = parse_otb_tree(ROOT / "assets" / "items" / "items.otb")
    mapping: dict[int, int] = {}
    for index, node in enumerate(root.children):
        server_id, client_id = _otb_node_ids(node, f"preflight-item-{index}")
        if server_id is not None and client_id is not None:
            mapping[server_id] = client_id
    expected = {BASE_WATER_SERVER_ID: BASE_WATER_CLIENT_ID}
    expected.update({sid: int(spec["client_id"]) for sid, spec in BORDERS.items()})
    actual = {sid: mapping.get(sid) for sid in expected}
    if actual != expected:
        raise ValueError(f"mapeamento OTB divergente: esperado={expected}, atual={actual}")
    if max(mapping) != TARGET_SERVER_START - 1:
        raise ValueError(
            f"max Server ID mudou: esperado {TARGET_SERVER_START - 1}, atual {max(mapping)}"
        )
    return expected


def build_palette() -> tuple[dict[tuple[int, int, int, int], tuple[int, int, int, int]], float]:
    report = json.loads(PALETTE_REPORT.read_text(encoding="utf-8"))
    palette = {
        tuple(entry["from"]): tuple(entry["to"])
        for entry in report["palette"]
    }
    ratios = [
        new[channel] / old[channel]
        for old, new in palette.items()
        for channel in range(3)
        if old[channel]
    ]
    factor = float(np.median(np.asarray(ratios, dtype=np.float32)))
    if not 0.72 < factor < 0.74:
        raise ValueError(f"fator escuro inesperado: {factor}")
    return palette, factor


def darken_pixels(
    pixels: np.ndarray,
    palette: dict[tuple[int, int, int, int], tuple[int, int, int, int]],
    fallback_factor: float,
) -> np.ndarray:
    output = pixels.copy()
    flat_before = pixels.reshape(-1, 4)
    flat_after = output.reshape(-1, 4)
    for index, value in enumerate(flat_before):
        rgba = tuple(int(channel) for channel in value)
        if rgba[3] == 0:
            continue
        target = palette.get(rgba)
        if target is None:
            target = tuple(
                int(round(int(channel) * fallback_factor)) for channel in rgba[:3]
            ) + (rgba[3],)
        flat_after[index] = target
    return output


def main() -> None:
    if OUTPUT_DIR.exists():
        raise FileExistsError(f"pasta de saida ja existe: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True)
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)

    otb_mapping = verify_otb_mapping()
    palette, fallback_factor = build_palette()
    palette_colors = set(palette)
    palette_colors.add((70, 114, 137, 255))

    base_path = find_export(BASE_WATER_SERVER_ID, BASE_WATER_CLIENT_ID)
    base = load_rgba(base_path)
    if base.shape != (FRAME_SIZE * FRAMES, FRAME_SIZE, 4):
        raise ValueError(f"layout da agua base diverge: {base.shape}")
    dark_base = darken_pixels(base, palette, fallback_factor)

    generated: list[dict[str, object]] = []
    manifest_rows: list[dict[str, object]] = []

    deep_path = OUTPUT_DIR / "01-deep-water-source-4825.png"
    save_rgba(deep_path, dark_base)
    generated.append({
        "kind": "deep_water",
        "source_server_id": BASE_WATER_SERVER_ID,
        "path": deep_path.relative_to(ROOT).as_posix(),
        "size": [FRAME_SIZE, FRAME_SIZE * FRAMES],
        "sha256": sha256(deep_path),
    })
    manifest_rows.append({
        "sequence": 1,
        "source_server_id": BASE_WATER_SERVER_ID,
        "target_server_id": TARGET_SERVER_START,
        "target_client_id": TARGET_CLIENT_START,
        "source_path": deep_path.name,
        "frame_width": FRAME_SIZE,
        "frame_height": FRAME_SIZE,
        "frames": FRAMES,
        "frame_duration_ms": DURATION_MS,
        "animation_async": 1,
        "layers": 1,
        "pattern_x": 1,
        "pattern_y": 1,
        "pattern_z": 1,
    })

    sequence = 2
    target_server_id = TARGET_SERVER_START + 1
    target_client_id = TARGET_CLIENT_START + 1
    border_sources: dict[int, tuple[np.ndarray, np.ndarray, dict[str, int]]] = {}

    for server_id, spec in BORDERS.items():
        client_id = int(spec["client_id"])
        pattern_x = int(spec["pattern_x"])
        pattern_y = int(spec["pattern_y"])
        original_path = find_export(server_id, client_id)
        supplied_dark_path = find_dark_border(server_id, client_id)
        original = load_rgba(original_path)
        supplied_dark = load_rgba(supplied_dark_path)
        expected_shape = (
            FRAME_SIZE * FRAMES * pattern_y,
            FRAME_SIZE * pattern_x,
            4,
        )
        if original.shape != expected_shape or supplied_dark.shape != expected_shape:
            raise ValueError(f"layout da borda {server_id} diverge")
        border_sources[server_id] = (original, supplied_dark, spec)

        output = np.zeros_like(original)
        for frame in range(FRAMES):
            clear_frame = base[
                frame * FRAME_SIZE : (frame + 1) * FRAME_SIZE, :, :
            ]
            dark_frame = dark_base[
                frame * FRAME_SIZE : (frame + 1) * FRAME_SIZE, :, :
            ]
            for pattern_y_index in range(pattern_y):
                y0 = (frame * pattern_y + pattern_y_index) * FRAME_SIZE
                for pattern_x_index in range(pattern_x):
                    x0 = pattern_x_index * FRAME_SIZE
                    source_tile = original[
                        y0 : y0 + FRAME_SIZE, x0 : x0 + FRAME_SIZE, :
                    ]
                    water_mask = np.array(
                        [tuple(int(c) for c in pixel) in palette_colors for pixel in source_tile.reshape(-1, 4)],
                        dtype=bool,
                    ).reshape(FRAME_SIZE, FRAME_SIZE)
                    if not water_mask.any():
                        # The narrowest diagonal borders contain only a few colors;
                        # infer their water-facing side from the exact recolor difference.
                        dark_tile = supplied_dark[
                            y0 : y0 + FRAME_SIZE, x0 : x0 + FRAME_SIZE, :
                        ]
                        water_mask = np.any(source_tile != dark_tile, axis=2)
                    if not water_mask.any():
                        raise ValueError(
                            f"nao foi possivel inferir o lado da agua: SID {server_id}, "
                            f"frame {frame}, pattern {pattern_x_index}/{pattern_y_index}"
                        )
                    inside = distance_to(~water_mask)
                    outside = distance_to(water_mask)
                    signed = np.where(water_mask, inside, -outside)
                    strength = quantize_blend(smoothstep((signed + 8.0) / 16.0))
                    output[
                        y0 : y0 + FRAME_SIZE, x0 : x0 + FRAME_SIZE, :
                    ] = blend_rgba(clear_frame, dark_frame, strength)

        path = OUTPUT_DIR / f"{sequence:02d}-open-water-transition-mask-{server_id}.png"
        save_rgba(path, output)
        generated.append({
            "kind": "open_water_transition",
            "mask_source_server_id": server_id,
            "property_source_server_id": BASE_WATER_SERVER_ID,
            "path": path.relative_to(ROOT).as_posix(),
            "size": [int(output.shape[1]), int(output.shape[0])],
            "pattern_x": pattern_x,
            "pattern_y": pattern_y,
            "sha256": sha256(path),
        })
        manifest_rows.append({
            "sequence": sequence,
            "source_server_id": BASE_WATER_SERVER_ID,
            "target_server_id": target_server_id,
            "target_client_id": target_client_id,
            "source_path": path.name,
            "frame_width": FRAME_SIZE,
            "frame_height": FRAME_SIZE,
            "frames": FRAMES,
            "frame_duration_ms": DURATION_MS,
            "animation_async": 1,
            "layers": 1,
            "pattern_x": pattern_x,
            "pattern_y": pattern_y,
            "pattern_z": 1,
        })
        sequence += 1
        target_server_id += 1
        target_client_id += 1

    for server_id, (original, _, spec) in border_sources.items():
        pattern_x = int(spec["pattern_x"])
        pattern_y = int(spec["pattern_y"])
        output = original.copy()
        changed_water_pixels = 0
        preserved_nonwater_pixels = 0
        for frame in range(FRAMES):
            for pattern_y_index in range(pattern_y):
                y0 = (frame * pattern_y + pattern_y_index) * FRAME_SIZE
                for pattern_x_index in range(pattern_x):
                    x0 = pattern_x_index * FRAME_SIZE
                    tile = original[
                        y0 : y0 + FRAME_SIZE, x0 : x0 + FRAME_SIZE, :
                    ]
                    water_mask = np.array(
                        [tuple(int(c) for c in pixel) in palette_colors for pixel in tile.reshape(-1, 4)],
                        dtype=bool,
                    ).reshape(FRAME_SIZE, FRAME_SIZE)
                    if not water_mask.any():
                        preserved_nonwater_pixels += FRAME_SIZE * FRAME_SIZE
                        continue
                    distance_from_border = distance_to(~water_mask)
                    strength = quantize_blend(
                        smoothstep((distance_from_border - 1.0) / 10.0)
                    )
                    dark_tile = darken_pixels(tile, palette, fallback_factor)
                    blended = blend_rgba(tile, dark_tile, strength)
                    result_tile = tile.copy()
                    result_tile[water_mask] = blended[water_mask]
                    output[
                        y0 : y0 + FRAME_SIZE, x0 : x0 + FRAME_SIZE, :
                    ] = result_tile
                    changed_water_pixels += int(
                        np.any(result_tile[water_mask] != tile[water_mask], axis=1).sum()
                    )
                    preserved_nonwater_pixels += int((~water_mask).sum())

        nonwater_mask = np.array(
            [tuple(int(c) for c in pixel) not in palette_colors for pixel in original.reshape(-1, 4)],
            dtype=bool,
        ).reshape(original.shape[:2])
        if not np.array_equal(output[nonwater_mask], original[nonwater_mask]):
            raise ValueError(f"pedras/transparencia mudaram na borda {server_id}")
        path = OUTPUT_DIR / f"{sequence:02d}-shore-gradient-source-{server_id}.png"
        save_rgba(path, output)
        generated.append({
            "kind": "shore_gradient",
            "source_server_id": server_id,
            "path": path.relative_to(ROOT).as_posix(),
            "size": [int(output.shape[1]), int(output.shape[0])],
            "pattern_x": pattern_x,
            "pattern_y": pattern_y,
            "changed_water_pixels": changed_water_pixels,
            "preserved_nonwater_pixels": preserved_nonwater_pixels,
            "sha256": sha256(path),
        })
        manifest_rows.append({
            "sequence": sequence,
            "source_server_id": server_id,
            "target_server_id": target_server_id,
            "target_client_id": target_client_id,
            "source_path": path.name,
            "frame_width": FRAME_SIZE,
            "frame_height": FRAME_SIZE,
            "frames": FRAMES,
            "frame_duration_ms": DURATION_MS,
            "animation_async": 1,
            "layers": 1,
            "pattern_x": pattern_x,
            "pattern_y": pattern_y,
            "pattern_z": 1,
        })
        sequence += 1
        target_server_id += 1
        target_client_id += 1

    if len(manifest_rows) != 23:
        raise ValueError(f"quantidade inesperada de itens: {len(manifest_rows)}")
    if target_server_id - 1 != 25637 or target_client_id - 1 != 24752:
        raise ValueError("intervalos finais de IDs divergentes")

    fieldnames = [
        "sequence", "source_server_id", "target_server_id", "target_client_id",
        "source_path", "frame_width", "frame_height", "frames",
        "frame_duration_ms", "animation_async", "layers", "pattern_x",
        "pattern_y", "pattern_z",
    ]
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(manifest_rows)

    preview = Image.new("RGBA", (23 * 104, 136), (29, 31, 34, 255))
    draw = ImageDraw.Draw(preview)
    for index, entry in enumerate(generated):
        image = Image.open(ROOT / str(entry["path"])).convert("RGBA")
        pattern_y = int(entry.get("pattern_y", 1))
        first = image.crop((0, 0, min(image.width, 64), FRAME_SIZE * pattern_y))
        thumb = first.resize((first.width * 3, first.height * 3), Image.Resampling.NEAREST)
        x = index * 104
        preview.alpha_composite(thumb, (x, 24))
        draw.text((x, 4), str(manifest_rows[index]["target_server_id"]), fill="white")
    preview_path = DRAFT_DIR / "water-transitions-first-frame-preview.png"
    preview.crop((0, 0, 23 * 104, 136)).convert("RGB").save(preview_path)

    plan = {
        "operation": "import-cloned-items",
        "name": "Deep water and light-to-dark water transitions",
        "purpose": (
            "Add a complete animated light/dark-water transition family for all "
            "existing shoreline directions, plus matching shoreline gradients."
        ),
        "card": "https://trello.com/c/iypxbXLe",
        "source_server_to_client": otb_mapping,
        "target_server_id_range": [25615, 25637],
        "target_client_id_range": [24730, 24752],
        "item_count": 23,
        "source_png_directory": OUTPUT_DIR.relative_to(ROOT).as_posix(),
        "manifest": MANIFEST_PATH.relative_to(ROOT).as_posix(),
        "layout": {
            "frame_size": [32, 32],
            "frames": FRAMES,
            "duration_ms": DURATION_MS,
            "animation_async": True,
            "layers": 1,
            "patterns": "preserved from the corresponding canonical border mask",
        },
        "properties_policy": (
            "Deep/open-water items clone SID 4825; shoreline-gradient items clone "
            "SIDs 4644..4654. Preserve DAT/OTB/XML properties and old records; only "
            "new contiguous DAT/OTB records and sprites may be appended."
        ),
        "visual_policy": (
            "Literal deterministic blend of canonical light-water pixels with the "
            "approved dark-water palette. Preserve original rock pixels, alpha, "
            "geometry, texture, patterns and animation; use only nine intermediate "
            "blend levels. No generated-image pixels are used."
        ),
        "imagegen_concept_role": "reference only; excluded from every import PNG",
        "preview": preview_path.relative_to(ROOT).as_posix(),
    }
    PLAN_PATH.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report = {
        "passed": True,
        "method": "deterministic canonical-pixel palette blend",
        "source_water": {
            "server_id": BASE_WATER_SERVER_ID,
            "client_id": BASE_WATER_CLIENT_ID,
            "path": base_path.relative_to(ROOT).as_posix(),
            "sha256": sha256(base_path),
        },
        "palette_source": PALETTE_REPORT.relative_to(ROOT).as_posix(),
        "fallback_brightness_factor": fallback_factor,
        "generated_count": len(generated),
        "generated": generated,
        "manifest": MANIFEST_PATH.relative_to(ROOT).as_posix(),
        "manifest_sha256": sha256(MANIFEST_PATH),
        "checks": {
            "otb_source_mappings_exact": True,
            "target_ids_contiguous_after_baseline_max": True,
            "all_png_rgba_8bit_non_interlaced": True,
            "all_frames_32x32": True,
            "all_items_have_15_frames": True,
            "all_rocks_and_transparency_preserved_in_shore_items": True,
            "no_imagegen_pixels_used": True,
        },
    }
    GENERATION_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "passed": True,
        "generated_count": len(generated),
        "target_server_ids": [25615, 25637],
        "target_client_ids": [24730, 24752],
        "manifest": str(MANIFEST_PATH),
        "preview": str(preview_path),
        "report": str(GENERATION_REPORT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
