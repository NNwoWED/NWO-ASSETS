from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import zlib

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SOURCE = next((ROOT / "sprites").glob("port*iwagakure.ase"))
OUTPUT_DIR = ROOT / "sprites" / "portao-iwagakure-png"
PREVIEW_PATH = (
    ROOT
    / "drafts"
    / "portao-iwagakure-20261020"
    / "portao-iwagakure-preview-320x224.png"
)
REPORT_PATH = ROOT / "reports" / "export-portao-iwagakure-ase-pieces-20261020.json"
GRID_SIZE = 32
MAX_PIECE_SIZE = 96

LAYER_SLUGS = {
    "portão": "portao",
    "pilar baixo": "pilar-baixo",
    "pilar meio": "pilar-meio",
    "casinha pilar": "casinha-pilar",
    "p baixo telhadinho": "pilar-baixo-telhadinho",
    "telhadinho": "telhadinho",
}


def parse_aseprite() -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, int]]:
    data = SOURCE.read_bytes()
    file_size, magic, frames, canvas_width, canvas_height, depth = struct.unpack_from(
        "<IHHHHH", data, 0
    )
    if file_size != len(data) or magic != 0xA5E0 or frames != 1 or depth != 32:
        raise ValueError("ASE deve estar integro, em RGBA 32-bit e possuir um frame")

    position = 128
    _, frame_magic, old_chunks = struct.unpack_from("<IHH", data, position)
    if frame_magic != 0xF1FA:
        raise ValueError("frame ASE invalido")
    chunks = struct.unpack_from("<I", data, position + 12)[0] or old_chunks
    position += 16

    layers: list[dict[str, object]] = []
    cels: list[dict[str, object]] = []
    for _ in range(chunks):
        size, chunk_type = struct.unpack_from("<IH", data, position)
        if chunk_type == 0x2004:
            flags, kind, child, _, _, blend, opacity = struct.unpack_from(
                "<HHHHHHB", data, position + 6
            )
            name_length = struct.unpack_from("<H", data, position + 22)[0]
            name = data[
                position + 24 : position + 24 + name_length
            ].decode("utf-8")
            layers.append(
                {
                    "name": name,
                    "flags": flags,
                    "kind": kind,
                    "child": child,
                    "blend": blend,
                    "opacity": opacity,
                }
            )
        elif chunk_type == 0x2005:
            layer, x, y, opacity, cel_type, z_index = struct.unpack_from(
                "<HhhBHh", data, position + 6
            )
            if cel_type not in (0, 2):
                raise ValueError(f"tipo de cel nao suportado: {cel_type}")
            width, height = struct.unpack_from("<HH", data, position + 22)
            payload = data[position + 26 : position + size]
            raw = zlib.decompress(payload) if cel_type == 2 else payload
            if len(raw) != width * height * 4:
                raise ValueError("payload RGBA do cel diverge")
            cels.append(
                {
                    "layer": layer,
                    "x": x,
                    "y": y,
                    "opacity": opacity,
                    "z_index": z_index,
                    "width": width,
                    "height": height,
                    "raw": raw,
                }
            )
        position += size

    if len(layers) != 6 or len(cels) != 6:
        raise ValueError(
            f"estrutura inesperada: layers={len(layers)}, cels={len(cels)}"
        )
    if any(
        not (int(layer["flags"]) & 1) or int(layer["blend"]) != 0
        for layer in layers
    ):
        raise ValueError("todas as camadas devem estar visiveis e usar blend normal")

    return layers, cels, {
        "canvas_width": canvas_width,
        "canvas_height": canvas_height,
        "depth": depth,
        "frames": frames,
        "source_size": len(data),
    }


def save_png(
    path: Path,
    image: Image.Image,
    *,
    layer_name: str,
    rectangle: tuple[int, int, int, int],
) -> dict[str, object]:
    image.save(path, format="PNG", optimize=False, compress_level=9)
    raw = path.read_bytes()
    if (
        raw[:8] != b"\x89PNG\r\n\x1a\n"
        or raw[24] != 8
        or raw[25] != 6
        or raw[28] != 0
    ):
        raise ValueError(f"PNG fora do padrao RGBA 8-bit nao entrelacado: {path}")
    bbox = image.getbbox()
    return {
        "file": path.relative_to(ROOT).as_posix(),
        "layer": layer_name,
        "rect_in_compact_canvas": list(rectangle),
        "size": list(image.size),
        "nonempty_bbox": list(bbox) if bbox else None,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest().upper(),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    for old_png in OUTPUT_DIR.glob("*.png"):
        old_png.unlink()

    layers, cels, metadata = parse_aseprite()
    origin_x, origin_y = 82, 114
    compact_width, compact_height = 320, 224
    layer_canvases: list[Image.Image] = []

    for cel in cels:
        layer_index = int(cel["layer"])
        layer = layers[layer_index]
        image = Image.frombytes(
            "RGBA",
            (int(cel["width"]), int(cel["height"])),
            cel["raw"],
        )
        effective_opacity = int(cel["opacity"]) * int(layer["opacity"])
        if effective_opacity != 255 * 255:
            alpha = image.getchannel("A").point(
                lambda value: value * effective_opacity // (255 * 255)
            )
            image.putalpha(alpha)
        canvas = Image.new(
            "RGBA", (compact_width, compact_height), (0, 0, 0, 0)
        )
        canvas.alpha_composite(
            image,
            (int(cel["x"]) - origin_x, int(cel["y"]) - origin_y),
        )
        layer_canvases.append(canvas)

    flattened = Image.new(
        "RGBA", (compact_width, compact_height), (0, 0, 0, 0)
    )
    for canvas in layer_canvases:
        flattened.alpha_composite(canvas)

    save_png(
        PREVIEW_PATH,
        flattened,
        layer_name="composite-preview",
        rectangle=(0, 0, compact_width, compact_height),
    )

    pieces: list[tuple[str, int, tuple[int, int, int, int]]] = []
    sequence = 1
    for layer_index, canvas in enumerate(layer_canvases):
        bbox = canvas.getbbox()
        if bbox is None:
            continue
        aligned_left = (bbox[0] // GRID_SIZE) * GRID_SIZE
        aligned_top = (bbox[1] // GRID_SIZE) * GRID_SIZE
        aligned_right = min(
            compact_width,
            ((bbox[2] + GRID_SIZE - 1) // GRID_SIZE) * GRID_SIZE,
        )
        aligned_bottom = min(
            compact_height,
            ((bbox[3] + GRID_SIZE - 1) // GRID_SIZE) * GRID_SIZE,
        )
        layer_name = str(layers[layer_index]["name"])
        try:
            slug = LAYER_SLUGS[layer_name]
        except KeyError as error:
            raise ValueError(f"camada sem slug deterministico: {layer_name}") from error

        for top in range(aligned_top, aligned_bottom, MAX_PIECE_SIZE):
            bottom = min(top + MAX_PIECE_SIZE, aligned_bottom)
            for left in range(aligned_left, aligned_right, MAX_PIECE_SIZE):
                right = min(left + MAX_PIECE_SIZE, aligned_right)
                rectangle = (left, top, right, bottom)
                piece = canvas.crop(rectangle)
                if piece.getbbox() is None:
                    continue
                width, height = piece.size
                if (
                    width % GRID_SIZE
                    or height % GRID_SIZE
                    or width > MAX_PIECE_SIZE
                    or height > MAX_PIECE_SIZE
                ):
                    raise ValueError(
                        f"recorte fora da grade/limite: {slug} {rectangle}"
                    )
                filename = (
                    f"{sequence:02d}-{slug}_x{left:03d}_y{top:03d}_"
                    f"{width}x{height}.png"
                )
                pieces.append((filename, layer_index, rectangle))
                sequence += 1

    outputs = []
    for filename, layer_index, rectangle in pieces:
        piece = layer_canvases[layer_index].crop(rectangle)
        outputs.append(
            save_png(
                OUTPUT_DIR / filename,
                piece,
                layer_name=str(layers[layer_index]["name"]),
                rectangle=rectangle,
            )
        )

    reassembled = Image.new(
        "RGBA", (compact_width, compact_height), (0, 0, 0, 0)
    )
    for output, (_, _, rectangle) in zip(outputs, pieces):
        piece = Image.open(ROOT / str(output["file"])).convert("RGBA")
        reassembled.alpha_composite(piece, (rectangle[0], rectangle[1]))
    if reassembled.tobytes() != flattened.tobytes():
        raise ValueError("as pecas nao recompõem exatamente o PNG completo")

    source_bytes = SOURCE.read_bytes()
    report = {
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest().upper(),
        "ase": {
            "canvas": [metadata["canvas_width"], metadata["canvas_height"]],
            "depth": metadata["depth"],
            "frames": metadata["frames"],
            "layers": len(layers),
            "cels": len(cels),
        },
        "method": (
            "camadas RGBA achatadas em blend normal; recortes alinhados a "
            "32 px; padding transparente; sem redimensionamento ou suavizacao"
        ),
        "compact_canvas": {
            "origin_in_ase": [origin_x, origin_y],
            "size": [compact_width, compact_height],
            "content_bbox": list(flattened.getbbox()),
        },
        "reference": {
            "name": "Portao de Konohagakure",
            "server_id_range": [22376, 22430],
            "item_count": 55,
        },
        "piece_count": len(pieces),
        "preview": PREVIEW_PATH.relative_to(ROOT).as_posix(),
        "verification": {
            "pieces_reassemble_composite_pixel_exact": True,
            "pieces_rgba_8bit_non_interlaced": True,
            "piece_dimensions_multiple_of_32": True,
            "piece_max_dimension": MAX_PIECE_SIZE,
            "resized": False,
        },
        "outputs": outputs,
        "passed": True,
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_dir": str(OUTPUT_DIR),
                "piece_count": len(pieces),
                "preview": PREVIEW_PATH.relative_to(ROOT).as_posix(),
                "report": str(REPORT_PATH),
                "passed": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
