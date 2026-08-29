#!/usr/bin/env python3
"""Comparador OTBM determinístico e estritamente somente leitura."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import zipfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator

START, ESCAPE, END = 0xFE, 0xFD, 0xFF
ATTR_DESCRIPTION, ATTR_EXT_SPAWN, ATTR_EXT_HOUSE = 1, 11, 13
ATTR_NAMES = {
    ATTR_DESCRIPTION: "description",
    ATTR_EXT_SPAWN: "spawn_file",
    ATTR_EXT_HOUSE: "house_file",
}


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


@contextmanager
def open_source(spec: str) -> Iterator[tuple[BinaryIO, dict[str, str]]]:
    """Abrir arquivo ou membro ZIP sem criar arquivos temporários."""
    if "::" not in spec:
        path = Path(spec)
        with path.open("rb") as stream:
            yield stream, {"container": str(path), "member": ""}
        return

    archive_name, member = spec.split("::", 1)
    archive = Path(archive_name)
    with zipfile.ZipFile(archive, "r") as bundle:
        info = bundle.getinfo(member)
        if info.is_dir():
            raise ValueError(f"{spec}: membro ZIP é diretório")
        with bundle.open(info, "r") as stream:
            yield stream, {"container": str(archive), "member": member}


def _logical_byte(stream: BinaryIO) -> tuple[int, bool] | None:
    raw = stream.read(1)
    if not raw:
        return None
    value = raw[0]
    if value == ESCAPE:
        escaped = stream.read(1)
        if not escaped:
            raise ValueError("escape truncado")
        return escaped[0], True
    return value, False


def inspect_otbm(stream: BinaryIO) -> dict:
    digest = hashlib.sha256()
    size = 0
    raw = stream.read(4)
    digest.update(raw)
    size += len(raw)
    if len(raw) != 4:
        raise ValueError("arquivo menor que o identificador OTBM de 4 bytes")

    class HashingReader:
        def read(self, amount: int = -1) -> bytes:
            nonlocal size
            chunk = stream.read(amount)
            digest.update(chunk)
            size += len(chunk)
            return chunk

    reader = HashingReader()
    counts: Counter[int] = Counter()
    stack: list[dict] = []
    completed_payloads: dict[int, bytes] = {}
    max_depth = 0
    errors: list[str] = []

    try:
        while True:
            token = _logical_byte(reader)
            if token is None:
                break
            value, was_escaped = token
            if value == START and not was_escaped:
                if stack:
                    stack[-1]["has_child"] = True
                node_token = _logical_byte(reader)
                if node_token is None:
                    raise ValueError("início de nó truncado")
                node_type, _ = node_token
                counts[node_type] += 1
                stack.append(
                    {"type": node_type, "payload": bytearray(), "has_child": False}
                )
                max_depth = max(max_depth, len(stack))
            elif value == END and not was_escaped:
                if not stack:
                    raise ValueError("fim de nó sem início")
                node = stack.pop()
                if (
                    node["type"] in (0, 2)
                    and node["type"] not in completed_payloads
                ):
                    completed_payloads[node["type"]] = bytes(node["payload"])
            elif stack and not stack[-1]["has_child"]:
                if len(stack[-1]["payload"]) < 1_048_576:
                    stack[-1]["payload"].append(value)
        if stack:
            errors.append(f"{len(stack)} nó(s) sem fechamento")
    except ValueError as exc:
        errors.append(str(exc))

    # HashingReader recebeu todos os bytes consumidos; consumir eventual cauda após erro.
    while chunk := reader.read(1024 * 1024):
        pass

    root = completed_payloads.get(0, b"")
    header: dict[str, int | str | None] = {
        "identifier_hex": raw.hex(),
        "otbm_version": None,
        "width": None,
        "height": None,
        "items_major_version": None,
        "items_minor_version": None,
    }
    if len(root) >= 16:
        header.update(
            {
                "otbm_version": _u32(root, 0),
                "width": _u16(root, 4),
                "height": _u16(root, 6),
                "items_major_version": _u32(root, 8),
                "items_minor_version": _u32(root, 12),
            }
        )
    else:
        errors.append("payload do cabeçalho raiz ausente ou truncado")

    metadata: dict[str, str] = {}
    payload = completed_payloads.get(2, b"")
    position = 0
    while position < len(payload):
        attr = payload[position]
        position += 1
        if attr not in ATTR_NAMES:
            errors.append(f"atributo de metadados desconhecido {attr} no offset {position-1}")
            break
        if position + 2 > len(payload):
            errors.append(f"tamanho truncado do atributo {attr}")
            break
        length = _u16(payload, position)
        position += 2
        if position + length > len(payload):
            errors.append(f"valor truncado do atributo {attr}")
            break
        metadata[ATTR_NAMES[attr]] = payload[position : position + length].decode(
            "utf-8", "replace"
        )
        position += length

    return {
        "sha256": digest.hexdigest(),
        "size_bytes": size,
        "header": header,
        "metadata": metadata,
        "structure": {
            "node_count": sum(counts.values()),
            "max_depth": max_depth,
            "node_types": {str(key): counts[key] for key in sorted(counts)},
        },
        "parse_errors": errors,
    }


def _hash_xml(stream: BinaryIO) -> tuple[str, int, str | None]:
    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
        if len(prefix) < 8192:
            prefix.extend(chunk[: 8192 - len(prefix)])
    root = None
    text = bytes(prefix).lstrip()
    if text.startswith(b"<?xml"):
        close = text.find(b"?>")
        text = text[close + 2 :].lstrip() if close >= 0 else b""
    if text.startswith(b"<"):
        token = text[1:].split(None, 1)[0].split(b">", 1)[0].split(b"/", 1)[0]
        root = token.decode("utf-8", "replace") or None
    return digest.hexdigest(), size, root


def inspect_sidecars(source_spec: str, metadata: dict[str, str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    archive_name, separator, member = source_spec.partition("::")
    for field in ("spawn_file", "house_file"):
        reference = metadata.get(field)
        if not reference:
            continue
        record: dict = {"reference": reference, "exists": False}
        try:
            if separator:
                base = PurePosixPath(member).parent
                candidate = str(base / reference)
                with zipfile.ZipFile(archive_name, "r") as bundle:
                    with bundle.open(candidate, "r") as stream:
                        sha, size, root = _hash_xml(stream)
                record.update(
                    {"exists": True, "location": f"{archive_name}::{candidate}"}
                )
            else:
                candidate_path = Path(archive_name).parent / reference
                with candidate_path.open("rb") as stream:
                    sha, size, root = _hash_xml(stream)
                record.update({"exists": True, "location": str(candidate_path)})
            record.update({"sha256": sha, "size_bytes": size, "xml_root": root})
        except (FileNotFoundError, KeyError, zipfile.BadZipFile, OSError) as exc:
            record["error"] = type(exc).__name__
        result[field] = record
    return result


def analyze(label: str, spec: str) -> dict:
    with open_source(spec) as (stream, origin):
        report = inspect_otbm(stream)
    report.update({"label": label, "source": spec, "origin": origin})
    report["sidecars"] = inspect_sidecars(spec, report["metadata"])
    return report


def build_report(variants: list[tuple[str, str]]) -> dict:
    rows = [analyze(label, spec) for label, spec in variants]
    recommendation = (
        "Priorizar para validação funcional a variante sem erros de parsing e com "
        "sidecars referenciados disponíveis; se os candidatos permanecerem equivalentes "
        "nesses critérios, decidir pelo comportamento no servidor/editor. Esta análise "
        "não escolhe nem instala a variante canônica."
    )
    return {
        "schema_version": 1,
        "read_only": True,
        "variants": rows,
        "recommendation": recommendation,
        "decision_required": "CEO/produto deve escolher explicitamente a variante canônica.",
    }


def markdown(report: dict) -> str:
    columns = [
        "Variante", "SHA-256", "Bytes", "OTBM", "Dimensões", "Items", "Descrição",
        "Nós", "Prof.", "Sidecars", "Erros",
    ]
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in report["variants"]:
        header, metadata = row["header"], row["metadata"]
        sidecars = ", ".join(
            f"{name}={'ok' if value['exists'] else 'ausente'}"
            for name, value in sorted(row["sidecars"].items())
        ) or "nenhum"
        values = [
            row["label"],
            row["sha256"],
            str(row["size_bytes"]),
            str(header["otbm_version"]),
            f"{header['width']}×{header['height']}",
            f"{header['items_major_version']}.{header['items_minor_version']}",
            metadata.get("description", ""),
            str(row["structure"]["node_count"]),
            str(row["structure"]["max_depth"]),
            sidecars,
            "; ".join(row["parse_errors"]) or "nenhum",
        ]
        lines.append("| " + " | ".join(str(v).replace("|", "\\|") for v in values) + " |")
    lines.extend(
        ["", f"**Recomendação técnica:** {report['recommendation']}",
         "", f"**Gate:** {report['decision_required']}"]
    )
    return "\n".join(lines) + "\n"


def parse_variant(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("usar RÓTULO=CAMINHO")
    label, spec = value.split("=", 1)
    if not label or not spec:
        raise argparse.ArgumentTypeError("rótulo e caminho não podem ser vazios")
    return label, spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", action="append", type=parse_variant, required=True)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", help="arquivo de saída; stdout quando omitido")
    args = parser.parse_args(argv)
    if len(args.variant) < 2:
        parser.error("informe pelo menos duas variantes")
    report = build_report(args.variant)
    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else markdown(report)
    )
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
