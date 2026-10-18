from __future__ import annotations

from copy import deepcopy
from html import escape
import re
import xml.etree.ElementTree as ET

from .errors import FormatError
from .remake_xml import _ids, _item_spans


def _clone_fragment(fragment: str, element: ET.Element, target_id: int) -> str:
    ids = list(_ids(element))
    if len(ids) == 1 and "id" in element.attrib:
        opening_end = fragment.find(">")
        opening = fragment[: opening_end + 1]
        replaced, count = re.subn(
            r"(\bid\s*=\s*['\"])\d+(['\"])",
            lambda match: f"{match.group(1)}{escape(str(target_id))}{match.group(2)}",
            opening,
            count=1,
        )
        if count != 1:
            raise FormatError("items.xml: nao foi possivel trocar o ID da origem")
        return replaced + fragment[opening_end + 1 :]

    clone = deepcopy(element)
    attributes = {"id": str(target_id)}
    attributes.update(
        (name, value)
        for name, value in clone.attrib.items()
        if name not in {"id", "fromid", "toid"}
    )
    clone.attrib.clear()
    clone.attrib.update(attributes)
    return ET.tostring(clone, encoding="unicode", short_empty_elements=True)


def clone_xml_definitions(
    source_xml: bytes, target_to_source: dict[int, int]
) -> tuple[bytes, dict[str, object]]:
    """Clone XML item definitions, including definitions declared as ID ranges."""

    try:
        xml = source_xml.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FormatError(f"items.xml nao e UTF-8: {exc}") from exc
    spans = _item_spans(xml)
    source_ids = set(target_to_source.values())
    target_ids = set(target_to_source)
    source_fragments: dict[int, tuple[str, ET.Element]] = {}
    target_fragments: dict[int, tuple[str, ET.Element]] = {}
    for start, end, element in spans:
        ids = list(_ids(element))
        id_set = set(ids)
        fragment = xml[start:end]
        for target_id in target_ids & id_set:
            if target_id in target_fragments:
                raise FormatError(f"items.xml: destino {target_id} duplicado")
            target_fragments[target_id] = (fragment, element)
        for source_id in source_ids & id_set:
            if source_id in source_fragments:
                raise FormatError(f"items.xml: origem {source_id} definida duas vezes")
            source_fragments[source_id] = (fragment, element)

    clones: list[str] = []
    already_exact = 0
    target_ids_with_definition: list[int] = []
    for target_id, source_id in target_to_source.items():
        source = source_fragments.get(source_id)
        if source is None:
            continue
        expected_fragment = _clone_fragment(source[0], source[1], target_id)
        target_ids_with_definition.append(target_id)
        existing = target_fragments.get(target_id)
        if existing is not None:
            existing_fragment = _clone_fragment(existing[0], existing[1], target_id)
            if existing_fragment != expected_fragment:
                raise FormatError(
                    f"items.xml: destino {target_id} existe mas difere da origem {source_id}"
                )
            already_exact += 1
        else:
            clones.append(expected_fragment)
    if not clones:
        return source_xml, {
            "source_definitions": len(source_fragments),
            "target_definitions_written": 0,
            "target_definitions_already_exact": already_exact,
            "target_ids": target_ids_with_definition,
        }
    close = xml.rfind("</items>")
    if close < 0:
        raise FormatError("items.xml: fechamento </items> ausente")
    newline = "\r\n" if "\r\n" in xml else "\n"
    insertion = newline.join(clones) + newline
    result = (xml[:close] + insertion + xml[close:]).encode("utf-8")
    try:
        ET.fromstring(result)
    except ET.ParseError as exc:
        raise FormatError(f"items.xml preparado invalido: {exc}") from exc
    return result, {
        "source_definitions": len(source_fragments),
        "target_definitions_written": len(clones),
        "target_definitions_already_exact": already_exact,
        "target_ids": target_ids_with_definition,
    }
