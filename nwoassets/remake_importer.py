from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re
import struct

from .atomic import atomic_binary_output
from .client import inspect_dat, inspect_spr
from .content import sha256_file
from .errors import FormatError
from .importer import (
    _commit_transaction,
    _otb_sprite_hashes,
    _remove_if_exists,
    _sha256_segment,
    _transaction_path,
    verify_sprite_hash_algorithm,
)
from .obd import (
    ObdItem,
    dat_properties_from_obd,
    encode_obd_appearance,
    make_obd_otb_node,
    read_obd_item,
)
from .otb import OtbNode, inspect_otb, parse_otb_tree
from .otb import NODE_END, NODE_START
from .otbm import (
    OTBM_HOUSETILE,
    OTBM_ITEM,
    OTBM_TILE,
    OTBM_TILE_AREA,
    _next_marker,
    _node_data,
    _parse_tile_data,
)
from .otfi import OtfiConfig, parse_otfi
from .pipeline import inspect_client
from .remake_catalog import remove_remake_catalog_entries
from .remake_xml import replace_remake_xml
from .roundtrip import append_spr_blocks, scan_dat_record_spans, write_otb_document
from .runtime_adopt import _attribute_u16, _parse_attributes
from .sprites import (
    decode_sprite_rgba,
    encode_sprite_rgba,
    read_spr_blocks,
    sprite_hash,
)
from .versioning import create_version, require_asset_layout


@dataclass(frozen=True)
class RemakeEntry:
    sequence: int
    server_id: int
    client_id: int
    source_client_id: int
    source_path: Path


def read_remake_manifest(path: Path) -> list[RemakeEntry]:
    path = path.resolve()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {
            "sequence", "server_id", "client_id", "source_client_id", "source_path"
        }
        if set(reader.fieldnames or ()) != expected:
            raise FormatError(f"{path}: cabeçalho esperado: {sorted(expected)}")
        entries: list[RemakeEntry] = []
        for line, row in enumerate(reader, 2):
            try:
                sequence = int(row["sequence"])
                server_id = int(row["server_id"])
                client_id = int(row["client_id"])
                source_client_id = int(row["source_client_id"])
            except (TypeError, ValueError) as error:
                raise FormatError(f"{path}:{line}: IDs inválidos") from error
            source_path = Path(row["source_path"])
            if not source_path.is_absolute():
                source_path = path.parent / source_path
            source_path = source_path.resolve()
            if not source_path.is_file():
                raise FormatError(f"{path}:{line}: OBD ausente: {source_path}")
            match = re.fullmatch(r"item_(\d+)_860v2-v2\.obd", source_path.name)
            if not match or int(match.group(1)) != source_client_id:
                raise FormatError(f"{path}:{line}: nome OBD não confere com origem")
            entries.append(
                RemakeEntry(sequence, server_id, client_id, source_client_id, source_path)
            )
    if not entries or [entry.sequence for entry in entries] != list(range(1, len(entries) + 1)):
        raise FormatError(f"{path}: sequências devem ser contínuas a partir de 1")
    for field in ("server_id", "client_id", "source_client_id", "source_path"):
        if len({getattr(entry, field) for entry in entries}) != len(entries):
            raise FormatError(f"{path}: {field} repetido")
    if [entry.server_id for entry in entries] != sorted(entry.server_id for entry in entries):
        raise FormatError(f"{path}: Server IDs devem estar em ordem crescente")
    if [entry.source_client_id for entry in entries] != sorted(
        entry.source_client_id for entry in entries
    ):
        raise FormatError(f"{path}: OBDs devem estar em ordem numérica crescente")
    return entries


def _otb_mappings(path: Path) -> tuple[dict[int, int], dict[int, list[int]]]:
    _, root = parse_otb_tree(path)
    by_server: dict[int, int] = {}
    by_client: dict[int, list[int]] = {}
    for node in root.children:
        attributes = _parse_attributes(node.data, str(path))
        server_id = _attribute_u16(attributes, 0x10)
        client_id = _attribute_u16(attributes, 0x11)
        if server_id is None or server_id in by_server:
            raise FormatError(f"{path}: Server ID OTB ausente ou duplicado")
        if client_id is not None:
            by_server[server_id] = client_id
            by_client.setdefault(client_id, []).append(server_id)
    return by_server, by_client


def _assert_map_targets_absent(path: Path, target_ids: set[int]) -> dict[str, int]:
    """Scan every OTBM item node and inline tile item before repurposing IDs."""

    hits: dict[int, int] = {}
    tile_count = item_node_count = 0
    with path.open("rb", buffering=1024 * 1024) as stream:
        if len(stream.read(4)) != 4 or stream.read(1) != bytes((NODE_START,)):
            raise FormatError(f"{path}: raiz OTBM inválida")
        stack: list[bool] = []
        while True:
            data, marker = _node_data(stream, str(path))
            if not data:
                raise FormatError(f"{path}: nó OTBM sem tipo")
            node_type = data[0]
            if node_type in {OTBM_TILE, OTBM_HOUSETILE}:
                tile_count += 1
                _, _, inline = _parse_tile_data(data, str(path))
                for entry in inline:
                    server_id = int(entry["server_id"])
                    if server_id in target_ids:
                        hits[server_id] = hits.get(server_id, 0) + 1
            elif node_type == OTBM_ITEM:
                item_node_count += 1
                if len(data) < 3:
                    raise FormatError(f"{path}: item OTBM truncado")
                server_id = struct.unpack_from("<H", data, 1)[0]
                if server_id in target_ids:
                    hits[server_id] = hits.get(server_id, 0) + 1
            if marker == NODE_START:
                stack.append(True)
                continue
            if marker == NODE_END:
                while stack:
                    marker = _next_marker(stream, str(path))
                    if marker == NODE_START:
                        break
                    stack.pop()
                else:
                    marker = None
            if marker is None:
                break
            if marker != NODE_START:
                raise FormatError(f"{path}: marcador OTBM inesperado {marker}")
    if hits:
        raise FormatError(f"destinos presentes no mapa: {sorted(hits.items())}")
    return {"tiles_scanned": tile_count, "item_nodes_scanned": item_node_count}


def _write_dat_remake_records(
    source: Path,
    destination: Path,
    otfi: OtfiConfig,
    replacements: dict[int, tuple[bytes, bytes]],
) -> None:
    if destination.exists() or source.resolve() == destination.resolve():
        raise FormatError("destino DAT temporário inválido")
    data = source.read_bytes()
    spans = scan_dat_record_spans(data, otfi, str(source))
    present = {span.thing_id for span in spans if span.category == "items"}
    if not set(replacements) <= present:
        raise FormatError(f"Client IDs DAT inexistentes: {sorted(set(replacements) - present)}")
    with atomic_binary_output(destination) as output:
        output.write(data[:12])
        for span in spans:
            if span.category == "items" and span.thing_id in replacements:
                properties, appearance = replacements[span.thing_id]
                output.write(properties)
                output.write(appearance)
            else:
                output.write(data[span.start:span.end])


def _write_otb_remake_nodes(
    source: Path, destination: Path, replacements: dict[int, tuple[int, ObdItem, bytes]]
) -> None:
    if destination.exists() or source.resolve() == destination.resolve():
        raise FormatError("destino OTB temporário inválido")
    version, root = parse_otb_tree(source)
    found: set[int] = set()
    children: list[OtbNode] = []
    for node in root.children:
        attributes = _parse_attributes(node.data, str(source))
        server_id = _attribute_u16(attributes, 0x10)
        if server_id not in replacements:
            children.append(node)
            continue
        if server_id in found or node.children:
            raise FormatError(f"Server ID {server_id}: nó OTB duplicado ou com filhos")
        client_id, item, digest = replacements[server_id]
        if _attribute_u16(attributes, 0x11) != client_id:
            raise FormatError(f"Server ID {server_id}: Client ID OTB divergente")
        children.append(
            make_obd_otb_node(
                item, server_id=server_id, client_id=client_id, sprite_hash=digest
            )
        )
        found.add(server_id)
    if found != set(replacements):
        raise FormatError(f"Server IDs OTB ausentes: {sorted(set(replacements) - found)}")
    write_otb_document(version, OtbNode(root.data, children), destination)


def import_obd_remakes(
    root: Path, manifest_path: Path, *, deep_spr: bool = True, dry_run: bool = False
) -> dict[str, object]:
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    layout = require_asset_layout(root)
    entries = read_remake_manifest(manifest_path)
    sprites_dir = (root / "sprites").resolve()
    if not all(entry.source_path.is_relative_to(sprites_dir) for entry in entries):
        raise FormatError("OBDs de entrada devem estar em NWO-ASSETS/sprites")
    baseline = inspect_client(root, deep_spr=deep_spr)
    if not baseline["passed"]:
        raise FormatError(f"baseline de origem reprovada: {baseline['errors']}")
    paths = {key: Path(value) for key, value in baseline["paths"].items()}
    paths["xml"] = layout["items"] / "items.xml"
    maps = sorted(layout["world"].glob("*.otbm"))
    if len(maps) != 1:
        raise FormatError("esperado exatamente um mapa canônico")
    by_server, by_client = _otb_mappings(paths["otb"])
    for entry in entries:
        if by_server.get(entry.server_id) != entry.client_id:
            raise FormatError(
                f"Server ID {entry.server_id}: Client ID {entry.client_id} "
                "não confere com OTB"
            )
        if by_client.get(entry.client_id) != [entry.server_id]:
            raise FormatError(f"Client ID {entry.client_id}: vínculo OTB ambíguo")
        if len(by_client.get(entry.source_client_id, [])) != 1:
            raise FormatError(f"Client ID origem {entry.source_client_id}: OTB ambíguo")
    otfi = parse_otfi(paths["otfi"])
    if not (otfi.extended and otfi.transparency and otfi.frame_durations):
        raise FormatError("OBD requer SPR estendido, transparência e frames DAT")
    hash_gate = verify_sprite_hash_algorithm(
        paths["dat"], paths["spr"], paths["otb"], otfi
    )
    if not hash_gate["passed"]:
        raise FormatError("SpriteHash da baseline não confere")
    old_sprite_count = int(baseline["spr"]["sprite_count"])
    next_sprite_id = old_sprite_count + 1
    blocks: list[bytes] = []
    expected_tiles: dict[int, bytes] = {}
    dat_replacements: dict[int, tuple[bytes, bytes]] = {}
    otb_replacements: dict[int, tuple[int, ObdItem, bytes]] = {}
    target_to_source: dict[int, int] = {}
    item_reports: list[dict[str, object]] = []
    for entry in entries:
        item = read_obd_item(entry.source_path)
        rgba_tiles = item.rgba_tiles()
        if len(rgba_tiles) > otfi.sprite_data_size:
            raise FormatError(f"OBD {entry.source_path}: sprites excedem OTFI")
        sprite_ids = tuple(range(next_sprite_id, next_sprite_id + len(rgba_tiles)))
        next_sprite_id += len(rgba_tiles)
        blocks.extend(encode_sprite_rgba(tile) for tile in rgba_tiles)
        expected_tiles.update(zip(sprite_ids, rgba_tiles))
        properties = dat_properties_from_obd(item)
        appearance = encode_obd_appearance(item, sprite_ids, otfi)
        digest = sprite_hash(rgba_tiles[: item.width * item.height])
        dat_replacements[entry.client_id] = (properties, appearance)
        otb_replacements[entry.server_id] = (entry.client_id, item, digest)
        target_to_source[entry.server_id] = by_client[entry.source_client_id][0]
        item_reports.append(
            {
                "sequence": entry.sequence,
                "server_id": entry.server_id,
                "client_id": entry.client_id,
                "source_server_id": target_to_source[entry.server_id],
                "source_client_id": entry.source_client_id,
                "source_path": str(entry.source_path),
                "source_sha256": sha256_file(entry.source_path),
                "layout": item.layout,
                "sprite_count": len(rgba_tiles),
                "sprite_ids": [sprite_ids[0], sprite_ids[-1]],
                "sprite_hash": digest.hex().upper(),
            }
        )
    original_xml = paths["xml"].read_bytes()
    prepared_xml, xml_report = replace_remake_xml(original_xml, target_to_source)
    if any(0x11 in {prop.flag for prop in item.parsed_properties} for _, item, _ in otb_replacements.values()):
        raise FormatError("OBD coletável exige regeneração completa do catálogo")
    catalog_path = root.parent / "Server-Data-Nwo" / "data" / "generated" / "items.lua"
    if not catalog_path.is_file():
        raise FormatError(f"catálogo gerado do servidor ausente: {catalog_path}")
    catalog_source = catalog_path.read_bytes()
    prepared_catalog, catalog_report = remove_remake_catalog_entries(
        catalog_source, set(otb_replacements)
    )
    if catalog_source == prepared_catalog:
        raise FormatError("nenhum registro obsoleto encontrado no catálogo gerado")
    protected = {
        "dat": paths["dat"],
        "spr": paths["spr"],
        "otb": paths["otb"],
        "xml": paths["xml"],
        "otfi": paths["otfi"],
        "otbm": maps[0],
        "catalog": catalog_path,
    }
    source_hashes = {name: sha256_file(path) for name, path in protected.items()}
    source_obd_hashes = {
        str(entry.source_path): sha256_file(entry.source_path) for entry in entries
    }
    map_scan = _assert_map_targets_absent(
        maps[0], {entry.server_id for entry in entries}
    )
    if dry_run:
        return {
            "root": str(root),
            "manifest": str(manifest_path),
            "dry_run": True,
            "item_count": len(entries),
            "new_sprite_count": len(blocks),
            "sprite_id_range": [old_sprite_count + 1, next_sprite_id - 1],
            "items": item_reports,
            "xml": xml_report,
            "catalog": catalog_report,
            "map_scan": map_scan,
            "source_hashes": source_hashes,
            "source_obd_hashes": source_obd_hashes,
            "passed": True,
        }
    pending = {
        name: _transaction_path(protected[name], "pending")
        for name in ("dat", "spr", "otb", "xml", "catalog")
    }
    if any(path.exists() for path in pending.values()):
        raise FormatError("arquivos temporários de importação já existem")
    backup = create_version(root)
    try:
        append_spr_blocks(paths["spr"], pending["spr"], otfi, blocks)
        _write_dat_remake_records(paths["dat"], pending["dat"], otfi, dat_replacements)
        _write_otb_remake_nodes(paths["otb"], pending["otb"], otb_replacements)
        with atomic_binary_output(pending["xml"]) as stream:
            stream.write(prepared_xml)
        with atomic_binary_output(pending["catalog"]) as stream:
            stream.write(prepared_catalog)

        pending_spr = inspect_spr(pending["spr"], otfi, deep=deep_spr)
        pending_dat = inspect_dat(
            pending["dat"],
            otfi,
            expected_metadata_reader=int(baseline["profile"]["metadata_reader"]),
            sprite_count=int(pending_spr["sprite_count"]),
        )
        pending_otb = inspect_otb(pending["otb"])
        if pending_otb["malformed_attributes"]:
            raise FormatError("OTB preparado possui atributos malformados")
        if int(pending_spr["sprite_count"]) != next_sprite_id - 1:
            raise FormatError("SPR preparado possui contagem divergente")
        if int(pending_dat["appearance"]["max_referenced_sprite_id"]) > next_sprite_id - 1:
            raise FormatError("DAT preparado referencia sprite inexistente")
        source_data = paths["dat"].read_bytes()
        staged_data = pending["dat"].read_bytes()
        source_spans = scan_dat_record_spans(source_data, otfi, str(paths["dat"]))
        staged_spans = scan_dat_record_spans(staged_data, otfi, str(pending["dat"]))
        if source_data[:12] != staged_data[:12] or len(source_spans) != len(staged_spans):
            raise FormatError("header ou quantidade de registros DAT mudou")
        for before, after in zip(source_spans, staged_spans):
            if (before.category, before.thing_id) != (after.category, after.thing_id):
                raise FormatError("ordem de registros DAT mudou")
            if before.category == "items" and before.thing_id in dat_replacements:
                expected = b"".join(dat_replacements[before.thing_id])
                if staged_data[after.start:after.end] != expected:
                    raise FormatError(f"Client ID {before.thing_id}: DAT não persistiu")
            elif source_data[before.start:before.end] != staged_data[after.start:after.end]:
                raise FormatError(f"registro DAT não alvo mudou: {before.category} {before.thing_id}")
        _, old_otb = parse_otb_tree(paths["otb"])
        _, new_otb = parse_otb_tree(pending["otb"])
        if len(old_otb.children) != len(new_otb.children):
            raise FormatError("quantidade de nós OTB mudou")
        for before, after in zip(old_otb.children, new_otb.children):
            sid = _attribute_u16(_parse_attributes(before.data, "OTB original"), 0x10)
            if sid in otb_replacements:
                if after.data != make_obd_otb_node(
                    otb_replacements[sid][1],
                    server_id=sid,
                    client_id=otb_replacements[sid][0],
                    sprite_hash=otb_replacements[sid][2],
                ).data:
                    raise FormatError(f"Server ID {sid}: OTB não persistiu")
            elif before.data != after.data:
                raise FormatError(f"Server ID {sid}: nó OTB não alvo mudou")
        if pending["xml"].read_bytes() != prepared_xml:
            raise FormatError("XML preparado não persistiu")
        if pending["catalog"].read_bytes() != prepared_catalog:
            raise FormatError("catálogo preparado não persistiu")
        old_body_start = int(baseline["spr"]["table_end"])
        new_body_start = int(pending_spr["table_end"])
        old_body_size = paths["spr"].stat().st_size - old_body_start
        if _sha256_segment(paths["spr"], old_body_start) != _sha256_segment(
            pending["spr"], new_body_start, old_body_size
        ):
            raise FormatError("payload de sprites antigos mudou")
        written = read_spr_blocks(pending["spr"], set(expected_tiles), otfi)
        for sprite_id, expected in expected_tiles.items():
            if decode_sprite_rgba(written[sprite_id], transparency=True) != expected:
                raise FormatError(f"Sprite ID {sprite_id}: pixels divergentes")
        staged_hashes = _otb_sprite_hashes(pending["otb"])
        for _, (client_id, _, digest) in otb_replacements.items():
            if staged_hashes.get(client_id) != [digest]:
                raise FormatError(f"Client ID {client_id}: SpriteHash OTB divergente")
        if source_hashes != {name: sha256_file(path) for name, path in protected.items()}:
            raise FormatError("baseline mudou durante a preparação do lote")
        if source_obd_hashes != {
            str(entry.source_path): sha256_file(entry.source_path) for entry in entries
        }:
            raise FormatError("OBD de origem mudou durante a preparação do lote")
        final = _commit_transaction(
            root,
            {protected[name]: pending[name] for name in ("dat", "spr", "otb", "xml", "catalog")},
            deep_spr=deep_spr,
        )
    except BaseException:
        _remove_if_exists(list(pending.values()))
        raise
    if not final["passed"]:
        raise FormatError("validação final falhou")
    if sha256_file(maps[0]) != source_hashes["otbm"]:
        raise FormatError("mapa mudou durante a importação")
    return {
        "root": str(root),
        "manifest": str(manifest_path),
        "version_backup": backup,
        "item_count": len(entries),
        "new_sprite_count": len(blocks),
        "sprite_id_range": [old_sprite_count + 1, next_sprite_id - 1],
        "items": item_reports,
        "xml": xml_report,
        "catalog": catalog_report,
        "map_scan": map_scan,
        "output_hashes": {name: sha256_file(protected[name]) for name in ("dat", "spr", "otb", "xml", "catalog")},
        "map_byte_equal": True,
        "transaction_committed": True,
        "final_validation_passed": True,
        "warnings": final["warnings"],
        "errors": [],
        "passed": True,
    }
