from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
import struct
import unicodedata
import xml.etree.ElementTree as ET

from .content import sha256_file
from .errors import FormatError
from .otfi import parse_otfi
from .png import PngImage, write_png_rgba
from .profiles import detect_profile
from .properties import read_otb_items
from .roundtrip import DatAppearance, DatRecordSpan, scan_dat_record_spans
from .sprites import decode_sprite_rgba, read_spr_blocks
from .versioning import require_asset_layout


EXPORT_CATEGORIES = {"items", "outfits", "effects", "missiles"}
ID_KINDS = {"client", "server"}


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", errors="ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")


def _item_names(path: Path) -> dict[int, str]:
    if not path.is_file():
        return {}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise FormatError(f"{path}: não foi possível ler os nomes dos itens: {exc}") from exc
    names: dict[int, str] = {}
    for element in root.iter("item"):
        raw_id = element.attrib.get("id")
        name = element.attrib.get("name")
        if raw_id and raw_id.isdigit() and name:
            names[int(raw_id)] = name
    return names


def compose_appearance_sheet(
    appearance: DatAppearance,
    rgba_by_sprite_id: dict[int, bytes],
    *,
    sprite_size: int = 32,
) -> PngImage:
    """Reproduce ThingType::exportImage's layer/pattern/frame sheet layout."""

    if sprite_size < 1:
        raise FormatError(f"sprite size inválido: {sprite_size}")
    expected_sprites = (
        appearance.width
        * appearance.height
        * appearance.layers
        * appearance.pattern_x
        * appearance.pattern_y
        * appearance.pattern_z
        * appearance.frames
    )
    if len(appearance.sprite_ids) != expected_sprites:
        raise FormatError(
            f"aparência declara {expected_sprites} sprites, "
            f"mas possui {len(appearance.sprite_ids)} IDs"
        )
    width = sprite_size * appearance.width * appearance.layers * appearance.pattern_x
    height = (
        sprite_size
        * appearance.height
        * appearance.frames
        * appearance.pattern_y
        * appearance.pattern_z
    )
    rgba = bytearray(width * height * 4)
    tile_stride = sprite_size * 4
    sheet_stride = width * 4

    for z in range(appearance.pattern_z):
        for y in range(appearance.pattern_y):
            for x in range(appearance.pattern_x):
                for layer in range(appearance.layers):
                    for frame in range(appearance.frames):
                        for tile_w in range(appearance.width):
                            for tile_h in range(appearance.height):
                                index = ((((((
                                    frame * appearance.pattern_z + z
                                ) * appearance.pattern_y + y
                                ) * appearance.pattern_x + x
                                ) * appearance.layers + layer
                                ) * appearance.height + tile_h
                                ) * appearance.width + tile_w)
                                sprite_id = appearance.sprite_ids[index]
                                tile = rgba_by_sprite_id.get(sprite_id)
                                if tile is None:
                                    raise FormatError(
                                        f"Sprite ID {sprite_id} não foi carregado para exportação"
                                    )
                                expected_tile_size = sprite_size * sprite_size * 4
                                if len(tile) != expected_tile_size:
                                    raise FormatError(
                                        f"Sprite ID {sprite_id} possui {len(tile)} bytes RGBA, "
                                        f"esperado {expected_tile_size}"
                                    )
                                destination_x = sprite_size * (
                                    appearance.width - tile_w - 1
                                    + appearance.width * x
                                    + appearance.width * appearance.pattern_x * layer
                                )
                                destination_y = sprite_size * (
                                    appearance.height - tile_h - 1
                                    + appearance.height * y
                                    + appearance.height * appearance.pattern_y * frame
                                    + appearance.height
                                    * appearance.pattern_y
                                    * appearance.frames
                                    * z
                                )
                                for row in range(sprite_size):
                                    source = row * tile_stride
                                    destination = (
                                        (destination_y + row) * sheet_stride
                                        + destination_x * 4
                                    )
                                    rgba[destination : destination + tile_stride] = tile[
                                        source : source + tile_stride
                                    ]
    return PngImage(width, height, bytes(rgba))


def _resolve_item_selections(
    ids: list[int],
    id_kind: str,
    spans: dict[int, DatRecordSpan],
    otb_path: Path,
    items_xml: Path,
) -> list[dict[str, object]]:
    otb_items = read_otb_items(otb_path)
    names = _item_names(items_xml)
    server_ids_by_client: defaultdict[int, list[int]] = defaultdict(list)
    for server_id, item in otb_items.items():
        client_id = int(item["client_id"])
        if client_id:
            server_ids_by_client[client_id].append(server_id)

    selections: list[dict[str, object]] = []
    if id_kind == "server":
        for server_id in ids:
            item = otb_items.get(server_id)
            if item is None:
                raise FormatError(f"Server ID {server_id} não existe no OTB")
            client_id = int(item["client_id"])
            if client_id == 0:
                raise FormatError(f"Server ID {server_id} não possui Client ID no OTB")
            if client_id not in spans:
                raise FormatError(
                    f"Server ID {server_id} aponta para Client ID DAT inexistente {client_id}"
                )
            selections.append(
                {
                    "requested_id": server_id,
                    "client_id": client_id,
                    "server_ids": [server_id],
                    "name": names.get(server_id),
                    "span": spans[client_id],
                }
            )
    else:
        for client_id in ids:
            if client_id not in spans:
                raise FormatError(f"Client ID {client_id} não existe no DAT")
            server_ids = sorted(server_ids_by_client.get(client_id, []))
            candidate_names = [names[value] for value in server_ids if value in names]
            selections.append(
                {
                    "requested_id": client_id,
                    "client_id": client_id,
                    "server_ids": server_ids,
                    "name": candidate_names[0] if candidate_names else None,
                    "span": spans[client_id],
                }
            )
    return selections


def _base_filename(category: str, selection: dict[str, object], id_kind: str) -> str:
    client_id = int(selection["client_id"])
    server_ids = [int(value) for value in selection["server_ids"]]
    parts: list[str] = []
    if category == "items":
        if id_kind == "server":
            parts.append(f"server-{int(selection['requested_id'])}")
            parts.append(f"client-{client_id}")
        else:
            parts.append(f"client-{client_id}")
            if len(server_ids) == 1:
                parts.append(f"server-{server_ids[0]}")
    else:
        parts.append(f"{category[:-1]}-{client_id}")
    name = selection.get("name")
    if isinstance(name, str) and (name_slug := _slug(name)):
        parts.append(name_slug)
    return "_".join(parts)


def export_pngs(
    root: Path,
    category: str,
    ids: list[int],
    *,
    id_kind: str = "client",
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    category = category.casefold()
    id_kind = id_kind.casefold()
    if category not in EXPORT_CATEGORIES:
        raise FormatError(
            f"categoria inválida {category!r}; use {sorted(EXPORT_CATEGORIES)}"
        )
    if id_kind not in ID_KINDS:
        raise FormatError(f"tipo de ID inválido {id_kind!r}; use client ou server")
    if category != "items" and id_kind == "server":
        raise FormatError("Server ID só pode ser usado para a categoria items")
    if not ids:
        raise FormatError("informe ao menos um ID para exportação")
    if len(ids) != len(set(ids)):
        raise FormatError("a lista de exportação contém IDs duplicados")
    if any(value < 1 for value in ids):
        raise FormatError("IDs de exportação devem ser positivos")

    layout = require_asset_layout(root)
    otfi_path = layout["860"] / "Tibia.otfi"
    otfi = parse_otfi(otfi_path)
    dat_path = layout["860"] / otfi.metadata_file
    spr_path = layout["860"] / otfi.sprites_file
    if not dat_path.is_file() or not spr_path.is_file():
        raise FormatError("DAT ou SPR definido pelo OTFI não foi encontrado")

    dat_data = dat_path.read_bytes()
    spans_all = scan_dat_record_spans(dat_data, otfi, str(dat_path))
    spans = {span.thing_id: span for span in spans_all if span.category == category}
    if category == "items":
        selections = _resolve_item_selections(
            ids,
            id_kind,
            spans,
            layout["items"] / "items.otb",
            layout["items"] / "items.xml",
        )
    else:
        missing = sorted(set(ids) - set(spans))
        if missing:
            raise FormatError(f"IDs DAT inexistentes em {category}: {missing}")
        selections = [
            {
                "requested_id": thing_id,
                "client_id": thing_id,
                "server_ids": [],
                "name": None,
                "span": spans[thing_id],
            }
            for thing_id in ids
        ]

    sprite_ids = {
        sprite_id
        for selection in selections
        for appearance in selection["span"].appearances  # type: ignore[union-attr]
        for sprite_id in appearance.sprite_ids
    }
    blocks = read_spr_blocks(spr_path, sprite_ids - {0}, otfi)
    rgba_by_sprite_id = {
        sprite_id: decode_sprite_rgba(block, transparency=otfi.transparency)
        for sprite_id, block in blocks.items()
    }
    rgba_by_sprite_id[0] = bytes(otfi.sprite_size * otfi.sprite_size * 4)

    destination_root = (
        root / "export" / category
        if output_dir is None
        else (output_dir if output_dir.is_absolute() else root / output_dir)
    ).resolve()
    pending: list[tuple[Path, PngImage, dict[str, object]]] = []
    for selection in selections:
        span = selection["span"]
        assert isinstance(span, DatRecordSpan)
        base = _base_filename(category, selection, id_kind)
        for group_index, appearance in enumerate(span.appearances):
            group_suffix = f"_group-{group_index}" if len(span.appearances) > 1 else ""
            path = destination_root / f"{base}{group_suffix}.png"
            if path.exists() and not overwrite:
                raise FormatError(
                    f"exportação já existe: {path}; use --overwrite para substituir"
                )
            image = compose_appearance_sheet(
                appearance,
                rgba_by_sprite_id,
                sprite_size=otfi.sprite_size,
            )
            metadata = {
                "requested_id": int(selection["requested_id"]),
                "client_id": int(selection["client_id"]),
                "server_ids": [int(value) for value in selection["server_ids"]],
                "name": selection.get("name"),
                "group_index": group_index,
                "width": image.width,
                "height": image.height,
                "layers": appearance.layers,
                "pattern_x": appearance.pattern_x,
                "pattern_y": appearance.pattern_y,
                "pattern_z": appearance.pattern_z,
                "frames": appearance.frames,
                "sprite_ids": list(appearance.sprite_ids),
            }
            pending.append((path, image, metadata))

    destination_root.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, object]] = []
    for path, image, metadata in pending:
        write_png_rgba(path, image)
        exported.append(
            {
                **metadata,
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    dat_signature = struct.unpack_from("<I", dat_data, 0)[0]
    with spr_path.open("rb") as stream:
        spr_signature_raw = stream.read(4)
    if len(spr_signature_raw) != 4:
        raise FormatError(f"{spr_path}: assinatura SPR truncada")
    profile = detect_profile(dat_signature, struct.unpack("<I", spr_signature_raw)[0])
    return {
        "root": str(root),
        "profile": profile.to_dict(),
        "category": category,
        "id_kind": id_kind,
        "requested_ids": ids,
        "output_dir": str(destination_root),
        "exported_count": len(exported),
        "exported": exported,
        "sources": {
            "dat": {"path": str(dat_path), "sha256": sha256_file(dat_path)},
            "spr": {"path": str(spr_path), "sha256": sha256_file(spr_path)},
        },
        "passed": True,
    }
