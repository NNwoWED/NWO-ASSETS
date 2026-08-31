from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import re
import struct
from typing import BinaryIO
import xml.etree.ElementTree as ET
import zipfile

from .errors import FormatError


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def classify(path: Path) -> str:
    if path.name.lower() in {".gitignore", ".gitattributes"}:
        return "git-config"
    suffix = path.suffix.lower()
    return {
        ".dat": "tibia-dat",
        ".spr": "tibia-spr",
        ".otfi": "tibia-otfi",
        ".otb": "items-otb",
        ".otbm": "map-otbm",
        ".otml": "otml-config",
        ".xml": "xml-config",
        ".zip": "zip-container",
        ".md": "documentation",
        ".txt": "text",
    }.get(suffix, "unknown")


def scan_directory(root: Path) -> dict[str, object]:
    root = root.resolve()
    ignored_directories = {
        ".git",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "export",
        "reports",
        "versions",
    }
    files: list[dict[str, object]] = []
    hashes: defaultdict[str, list[str]] = defaultdict(list)
    type_counts: Counter[str] = Counter()
    total_bytes = 0
    candidates = (
        path
        for path in root.rglob("*")
        if path.is_file()
        and not ignored_directories.intersection(path.relative_to(root).parts)
    )
    for path in sorted(
        candidates,
        key=lambda value: value.relative_to(root).as_posix().casefold(),
    ):
        relative = path.relative_to(root).as_posix()
        digest = sha256_file(path)
        file_type = classify(path)
        stat = path.stat()
        files.append(
            {
                "path": relative,
                "type": file_type,
                "size": stat.st_size,
                "sha256": digest,
                "modified_utc": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
        hashes[digest].append(relative)
        type_counts[file_type] += 1
        total_bytes += stat.st_size
    duplicates = [
        {"sha256": digest, "paths": paths}
        for digest, paths in hashes.items()
        if len(paths) > 1
    ]
    return {
        "root": str(root),
        "ignored_directories": sorted(ignored_directories),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "type_counts": dict(sorted(type_counts.items())),
        "duplicate_groups": duplicates,
        "files": files,
    }


def inspect_xml(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "latin-1"
        text = raw.decode(encoding)
    fragment = False
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        try:
            root = ET.fromstring(f"<nwoassets-fragment>{text}</nwoassets-fragment>")
            fragment = True
        except ET.ParseError as exc:
            raise FormatError(f"{path}: XML inválido: {exc}") from exc
    tags = Counter(element.tag for element in root.iter())
    numeric_ids: list[int] = []
    for element in root.iter():
        for name in ("id", "itemid", "clientId", "houseid"):
            value = element.attrib.get(name)
            if value and value.isdigit():
                numeric_ids.append(int(value))
    return {
        "path": str(path),
        "size": len(raw),
        "encoding": encoding,
        "fragment": fragment,
        "root": root.tag,
        "element_count": sum(tags.values()),
        "tag_counts": dict(sorted(tags.items())),
        "numeric_id_min": min(numeric_ids, default=None),
        "numeric_id_max": max(numeric_ids, default=None),
    }


_OTML_SECTION = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?://.*)?$")


def inspect_otml(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        encoding = "latin-1"
    lines = text.splitlines()
    sections = [
        match.group(1)
        for line in lines
        if (match := _OTML_SECTION.match(line))
    ]
    mojibake_markers = sum(text.count(marker) for marker in ("Ã", "Â", "�"))
    return {
        "path": str(path),
        "size": len(raw),
        "encoding": encoding,
        "line_count": len(lines),
        "top_level_sections": sections,
        "mojibake_marker_count": mojibake_markers,
    }


def _read_unescaped_node_data(stream: BinaryIO, *, start_consumed: bool = False) -> tuple[bytes, int]:
    if not start_consumed:
        marker = stream.read(1)
        if marker != b"\xFE":
            raise FormatError("marcador de início de nó 0xFE ausente")
    result = bytearray()
    while True:
        raw = stream.read(1)
        if not raw:
            raise FormatError("nó binário truncado")
        value = raw[0]
        if value == 0xFD:
            escaped = stream.read(1)
            if not escaped:
                raise FormatError("escape binário truncado")
            result.append(escaped[0])
        elif value in {0xFE, 0xFF}:
            return bytes(result), value
        else:
            result.append(value)


def _scan_node_tree(stream: BinaryIO, source: str) -> dict[str, object]:
    stream.seek(4)
    tree = stream.read()
    if not tree or tree[0] != 0xFE:
        raise FormatError(f"{source}: árvore OTBM não começa com 0xFE")
    if tree[-1] == 0xFD:
        raise FormatError(f"{source}: escape truncado no fim da árvore")
    # Cada 0xFD escapa exatamente o byte seguinte. Remover os pares escapados
    # antes da contagem também trata corretamente a sequência FD FD FE, na qual
    # o primeiro par representa um FD literal e o FE seguinte inicia um nó.
    structural = re.sub(b"\xFD.", b"", tree, flags=re.DOTALL)
    node_starts = structural.count(b"\xFE")
    node_ends = structural.count(b"\xFF")
    if node_starts != node_ends:
        raise FormatError(
            f"{source}: árvore desbalanceada ({node_starts} inícios, "
            f"{node_ends} fechamentos)"
        )
    return {
        "total_bytes_read": len(tree) + 4,
        "total_nodes": node_starts,
        "node_starts": node_starts,
        "node_ends": node_ends,
        "balanced": True,
    }


def inspect_otbm_stream(stream: BinaryIO, source: str) -> dict[str, object]:
    file_identifier_raw = stream.read(4)
    if len(file_identifier_raw) != 4:
        raise FormatError(f"{source}: header OTBM truncado")
    file_identifier = struct.unpack("<I", file_identifier_raw)[0]
    root_data, marker = _read_unescaped_node_data(stream)
    if len(root_data) < 17:
        raise FormatError(f"{source}: nó raiz OTBM curto demais")
    node_type = root_data[0]
    version = struct.unpack_from("<I", root_data, 1)[0]
    width, height = struct.unpack_from("<HH", root_data, 5)
    items_major, items_minor = struct.unpack_from("<II", root_data, 9)
    description = None
    if marker == 0xFE:
        child_data, _ = _read_unescaped_node_data(stream, start_consumed=True)
        if child_data and child_data[0] == 2:
            position = 1
            while position + 3 <= len(child_data):
                attribute = child_data[position]
                length = struct.unpack_from("<H", child_data, position + 1)[0]
                position += 3
                payload = child_data[position : position + length]
                position += length
                if attribute == 1:
                    description = payload.decode("latin-1", errors="replace")
    report = {
        "source": source,
        "file_identifier": file_identifier,
        "root_node_type": node_type,
        "map_version": version,
        "width": width,
        "height": height,
        "items_major_version": items_major,
        "items_minor_version": items_minor,
        "description": description,
    }
    report["tree"] = _scan_node_tree(stream, source)
    return report


def inspect_otbm(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        report = inspect_otbm_stream(stream, str(path))
    report["size"] = path.stat().st_size
    report["sha256"] = sha256_file(path)
    return report


def inspect_zip(path: Path) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            with archive.open(info) as stream:
                payload = stream.read()
            entry: dict[str, object] = {
                "name": info.filename,
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "sha256": hashlib.sha256(payload).hexdigest().upper(),
            }
            if info.filename.lower().endswith(".otbm"):
                entry["otbm"] = inspect_otbm_stream(
                    io.BytesIO(payload), f"{path}!/{info.filename}"
                )
            entries.append(entry)
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "entries": entries,
    }


def inspect_world(root: Path) -> dict[str, object]:
    world = root / "assets" / "world"
    if not world.is_dir():
        raise FormatError(f"{world}: diretório world não encontrado")
    maps = [inspect_otbm(path) for path in sorted(world.glob("*.otbm"))]
    zips = [inspect_zip(path) for path in sorted(world.glob("*.zip"))]
    xml = [inspect_xml(path) for path in sorted(world.glob("*.xml"))]
    hashes = [
        (entry["sha256"], entry["source"])
        for entry in maps
        if isinstance(entry.get("sha256"), str)
    ]
    for archive in zips:
        for entry in archive["entries"]:
            if entry["name"].lower().endswith(".otbm"):
                hashes.append((entry["sha256"], f"{archive['path']}!/{entry['name']}"))
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for digest, source in hashes:
        groups[str(digest)].append(str(source))
    return {
        "maps": maps,
        "archives": zips,
        "xml": xml,
        "map_variants": len(hashes),
        "identical_map_groups": [
            {"sha256": digest, "sources": sources}
            for digest, sources in groups.items()
            if len(sources) > 1
        ],
    }
