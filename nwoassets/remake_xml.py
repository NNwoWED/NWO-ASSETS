from __future__ import annotations

from html import escape
import re
import xml.etree.ElementTree as ET

from .errors import FormatError


_ITEM_START = re.compile(r"(?m)^[ \t]*<item\b")


def _item_spans(xml: str) -> list[tuple[int, int, ET.Element]]:
    spans: list[tuple[int, int, ET.Element]] = []
    for match in _ITEM_START.finditer(xml):
        start = match.start()
        tag_end = xml.find(">", match.end())
        if tag_end < 0:
            raise FormatError("items.xml: tag <item> sem fechamento")
        if xml[tag_end - 1] == "/":
            end = tag_end + 1
        else:
            close = xml.find("</item>", tag_end + 1)
            if close < 0:
                raise FormatError("items.xml: elemento <item> sem fechamento")
            end = close + len("</item>")
        try:
            element = ET.fromstring(xml[start:end])
        except ET.ParseError as error:
            raise FormatError(f"items.xml: elemento <item> inválido: {error}") from error
        spans.append((start, end, element))
    return spans


def _ids(element: ET.Element) -> range:
    if "id" in element.attrib:
        value = int(element.attrib["id"])
        return range(value, value + 1)
    if "fromid" in element.attrib and "toid" in element.attrib:
        return range(int(element.attrib["fromid"]), int(element.attrib["toid"]) + 1)
    raise FormatError("items.xml: item sem id ou fromid/toid")


def replace_remake_xml(
    source_xml: bytes, target_to_source: dict[int, int]
) -> tuple[bytes, dict[str, object]]:
    """Replace only selected XML definitions, preserving all unrelated bytes."""

    if not target_to_source or len(set(target_to_source.values())) != len(target_to_source):
        raise FormatError("mapeamento XML vazio ou com origem repetida")
    try:
        xml = source_xml.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FormatError(f"items.xml não é UTF-8: {error}") from error
    newline = "\r\n" if "\r\n" in xml else "\n"
    spans = _item_spans(xml)
    source_ids = set(target_to_source.values())
    target_ids = set(target_to_source)
    source_entries: dict[int, ET.Element] = {}
    target_entries: set[int] = set()
    for _, _, element in spans:
        ids = set(_ids(element))
        for server_id in ids & source_ids:
            if server_id in source_entries:
                raise FormatError(f"items.xml: origem {server_id} definida duas vezes")
            source_entries[server_id] = element
        target_entries.update(ids & target_ids)

    replacement_lines: list[str] = []
    named = 0
    for target_id, source_id in target_to_source.items():
        source = source_entries.get(source_id)
        if source is None:
            continue
        if len(source):
            raise FormatError(
                f"items.xml: origem {source_id} possui atributos filhos; "
                "clone explícito ainda não suportado"
            )
        attributes = {"id": str(target_id)}
        attributes.update(
            (name, value)
            for name, value in source.attrib.items()
            if name not in {"id", "fromid", "toid"}
        )
        encoded = " ".join(
            f'{name}="{escape(value, quote=True)}"'
            for name, value in attributes.items()
        )
        replacement_lines.append(f"\t<item {encoded} />{newline}")
        if attributes.get("name"):
            named += 1

    replacements = "".join(replacement_lines)
    output: list[str] = []
    cursor = 0
    inserted = False
    removed_entries = 0
    for start, end, element in spans:
        item_ids = set(_ids(element))
        affected = item_ids & target_ids
        if not affected:
            continue
        if affected != item_ids:
            raise FormatError(
                "items.xml: intervalo abrange IDs substituídos e preservados: "
                f"{sorted(item_ids)[:2]}...{sorted(item_ids)[-2:]}"
            )
        output.append(xml[cursor:start])
        if not inserted:
            output.append(replacements)
            inserted = True
        cursor = end
        if xml.startswith(newline, cursor):
            cursor += len(newline)
        removed_entries += 1
    if not inserted:
        raise FormatError("items.xml: nenhum destino possui definição a substituir")
    output.append(xml[cursor:])
    result = "".join(output).encode("utf-8")
    try:
        ET.fromstring(result)
    except ET.ParseError as error:
        raise FormatError(f"items.xml preparado inválido: {error}") from error
    return result, {
        "targets": len(target_to_source),
        "source_definitions": len(source_entries),
        "target_definitions_removed": len(target_entries),
        "target_elements_removed": removed_entries,
        "target_definitions_written": len(replacement_lines),
        "names_written": named,
    }
