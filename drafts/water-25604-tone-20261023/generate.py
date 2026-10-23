"""Darken only the water pixels of SID 25604 using the approved border palette."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from math import dist
from pathlib import Path
from statistics import median
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nwoassets.clone_item_importer import _otb_node_ids
from nwoassets.otb import parse_otb_tree
from nwoassets.otfi import parse_otfi
from nwoassets.roundtrip import read_dat_animation_timings, scan_dat_record_spans

SERVER_ID = 25604
CLIENT_ID = 24719
REFERENCE_SERVER_ID = 25606
SOURCE_EXPORT_DIR = ROOT / "export" / "water-border-25604-review-20261023"
WORK_DIR = ROOT / "sprites" / "water-25604-tone-20261023"
REPORT = ROOT / "reports" / "recolor-water-25604-20261023.json"
PLAN = ROOT / "reports" / "water-25604-tone-plan-20261023.json"
PREVIEW = ROOT / "drafts" / "water-25604-tone-20261023" / "preview.png"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> None:
    baseline = json.loads(
        (ROOT / "reports" / "validation-water-border-25604-before-20261023.json").read_text(encoding="utf-8")
    )
    if not baseline["passed"] or baseline["errors"]:
        raise ValueError("baseline reprovada")

    export_report = json.loads(
        (ROOT / "reports" / "export-water-border-25604-review-20261023.json").read_text(encoding="utf-8")
    )
    source_entry = next(entry for entry in export_report["exported"] if entry["requested_id"] == SERVER_ID)
    reference_entry = next(entry for entry in export_report["exported"] if entry["requested_id"] == REFERENCE_SERVER_ID)
    if source_entry["client_id"] != CLIENT_ID or source_entry["server_ids"] != [SERVER_ID]:
        raise ValueError("vinculo exclusivo SID/CID do alvo divergiu")
    expected_layout = (32, 960, 15, 1, 1, 2, 1)
    actual_layout = (
        source_entry["width"], source_entry["height"], source_entry["frames"],
        source_entry["layers"], source_entry["pattern_x"], source_entry["pattern_y"],
        source_entry["pattern_z"],
    )
    if actual_layout != expected_layout:
        raise ValueError(f"layout inesperado: {actual_layout}")

    _, otb_root = parse_otb_tree(ROOT / "assets" / "items" / "items.otb")
    nodes = [node for node in otb_root.children if _otb_node_ids(node, "preflight")[1] == CLIENT_ID]
    if len(nodes) != 1 or _otb_node_ids(nodes[0], "preflight")[0] != SERVER_ID:
        raise ValueError("Client ID alvo nao possui vinculo OTB exclusivo")

    dat = (ROOT / "assets" / "860" / "Tibia.dat").read_bytes()
    otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
    span = next(
        item for item in scan_dat_record_spans(dat, otfi, "preflight")
        if item.category == "items" and item.thing_id == CLIENT_ID
    )
    timing = read_dat_animation_timings(dat, otfi, "items", {CLIENT_ID}, "preflight")[CLIENT_ID]

    if WORK_DIR.exists():
        raise FileExistsError(f"pasta de saida ja existe: {WORK_DIR}")
    WORK_DIR.mkdir(parents=True)
    original = WORK_DIR / "original-server-25604_client-24719.png"
    original.write_bytes(Path(source_entry["path"]).read_bytes())
    image = Image.open(original).convert("RGBA")
    before = list(image.get_flattened_data())
    counts = Counter(before)

    palette_report = json.loads(
        (ROOT / "reports" / "recolor-water-border-4655-20261022.json").read_text(encoding="utf-8")
    )
    palette = {tuple(entry["from"]): tuple(entry["to"]) for entry in palette_report["palette"]}
    if len(palette) != 77:
        raise ValueError("tabela de paleta aprovada nao possui 77 cores")

    stone_colors = {
        (80, 77, 74, 255), (122, 117, 112, 255), (57, 55, 53, 255),
        (148, 144, 140, 255), (45, 43, 41, 255), (100, 96, 92, 255),
    }
    rare = (52, 204, 236, 255)
    if counts[rare] != 1:
        raise ValueError(f"quantidade inesperada da cor rara: {counts[rare]}")
    nearest = sorted(
        palette.items(), key=lambda pair: (dist(pair[0][:3], rare[:3]), pair[0])
    )[:8]
    factor = median(
        new[channel] / old[channel]
        for old, new in nearest
        for channel in range(3)
        if old[channel]
    )
    rare_target = tuple(round(channel * factor) for channel in rare[:3]) + (255,)
    if rare_target != (39, 153, 177, 255):
        raise ValueError(f"conversao rara inesperada: {rare_target}")
    palette[rare] = rare_target

    unknown = Counter(
        pixel for pixel in before
        if pixel[3] and pixel not in palette and pixel not in stone_colors
    )
    if unknown:
        raise ValueError(f"cores opacas nao classificadas: {unknown}")

    after = [palette.get(pixel, pixel) for pixel in before]
    changed = sum(old != new for old, new in zip(before, after))
    if changed != 12730:
        raise ValueError(f"quantidade inesperada de pixels alterados: {changed}")
    if not all(old == new for old, new in zip(before, after) if not old[3] or old in stone_colors):
        raise ValueError("pedras ou transparencia foram alteradas")
    if not all(old[3] == new[3] for old, new in zip(before, after)):
        raise ValueError("canal alpha foi alterado")

    output = Image.new("RGBA", image.size)
    output.putdata(after)
    target = WORK_DIR / "server-25604_client-24719.png"
    output.save(target, format="PNG", optimize=False, compress_level=9, interlace=False)
    if list(Image.open(target).convert("RGBA").get_flattened_data()) != after:
        raise ValueError("pixels persistidos divergem")

    manifest = WORK_DIR / "water-25604-tone-20261023.csv"
    manifest.write_text(
        "sequence,client_id,source_path,preserve_layout\n"
        "1,24719,server-25604_client-24719.png,1\n",
        encoding="utf-8",
    )

    plan = {
        "operation": "substituir",
        "name": "Shallow water border",
        "purpose": "match SID 25604 water tone to approved SID 25606 tone",
        "card": "https://trello.com/c/iypxbXLe",
        "server_id": SERVER_ID,
        "client_id": CLIENT_ID,
        "exclusive_otb_link_verified": True,
        "reference_server_id": REFERENCE_SERVER_ID,
        "source_png": target.relative_to(ROOT).as_posix(),
        "sheet_size": [32, 960],
        "frame_size": [32, 32],
        "frames": 15,
        "layers": 1,
        "pattern_x": 1,
        "pattern_y": 2,
        "pattern_z": 1,
        "animation_async": timing.animation_async,
        "durations": timing.durations,
        "properties_policy": "preserve all DAT/OTB properties, layout and timing; replace only target sprite pixels and SpriteHash",
        "dat_properties_sha256": hashlib.sha256(dat[span.start:span.properties_end]).hexdigest().upper(),
        "otb_before_hex": nodes[0].data.hex(),
        "map_sha256": sha256(ROOT / "assets" / "world" / "mapanovo.otbm"),
        "palette_reference": "reports/recolor-water-border-4655-20261022.json",
    }
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reference = Image.open(reference_entry["path"]).convert("RGBA")
    preview = Image.new("RGBA", (680, 320), (35, 35, 35, 255))
    draw = ImageDraw.Draw(preview)
    for index, (label, sample) in enumerate(
        [("25604 before", image), ("25604 corrected", output), ("25606 reference", reference)]
    ):
        draw.text((index * 225, 5), label, fill="white")
        crop = sample.crop((0, 0, 32, 64)).resize((128, 256), Image.Resampling.NEAREST)
        preview.alpha_composite(crop, (index * 225, 30))
    preview.convert("RGB").save(PREVIEW)

    report = {
        "passed": True,
        "changed_pixels": changed,
        "stone_pixels_preserved": sum(counts[color] for color in stone_colors),
        "transparent_pixels_preserved": counts[(0, 0, 0, 0)],
        "alpha_preserved": True,
        "layout_preserved": True,
        "exact_reference_colors": 77,
        "rare_color": {
            "from": rare,
            "to": rare_target,
            "pixels": counts[rare],
            "brightness_factor": factor,
            "nearest_reference_pairs": [
                {"from": old, "to": new} for old, new in nearest
            ],
        },
        "original_sha256": sha256(original),
        "recolor_sha256": sha256(target),
        "manifest_sha256": sha256(manifest),
        "plan": PLAN.relative_to(ROOT).as_posix(),
        "preview": PREVIEW.relative_to(ROOT).as_posix(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
