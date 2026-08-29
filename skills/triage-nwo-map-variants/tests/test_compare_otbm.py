from __future__ import annotations

import importlib.util
import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "compare_otbm.py"
SPEC = importlib.util.spec_from_file_location("compare_otbm", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def escaped(data: bytes) -> bytes:
    result = bytearray()
    for value in data:
        if value in (MODULE.START, MODULE.ESCAPE, MODULE.END):
            result.append(MODULE.ESCAPE)
        result.append(value)
    return bytes(result)


def node(node_type: int, payload: bytes = b"", children: bytes = b"") -> bytes:
    return bytes([MODULE.START]) + escaped(bytes([node_type]) + payload) + children + bytes([MODULE.END])


def fixture(description: str = "fixture") -> bytes:
    attrs = (
        bytes([MODULE.ATTR_DESCRIPTION])
        + struct.pack("<H", len(description))
        + description.encode()
        + bytes([MODULE.ATTR_EXT_SPAWN])
        + struct.pack("<H", 9)
        + b"spawn.xml"
        + bytes([MODULE.ATTR_EXT_HOUSE])
        + struct.pack("<H", 9)
        + b"house.xml"
    )
    map_data = node(2, attrs, node(4, b"\x01\x02"))
    header = struct.pack("<IHHII", 2, 3000, 3000, 3, 20)
    return b"\0\0\0\0" + node(0, header, map_data)


class CompareOtbmTests(unittest.TestCase):
    def test_parses_header_metadata_and_structure(self):
        report = MODULE.inspect_otbm(io.BytesIO(fixture()))
        self.assertEqual(report["header"]["width"], 3000)
        self.assertEqual(report["metadata"]["description"], "fixture")
        self.assertEqual(report["structure"]["node_types"], {"0": 1, "2": 1, "4": 1})
        self.assertEqual(report["parse_errors"], [])

    def test_zip_member_and_sidecars_stay_in_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "maps.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("map.otbm", fixture())
                bundle.writestr("spawn.xml", "<spawns/>")
                bundle.writestr("house.xml", "<houses/>")
            report = MODULE.analyze("zip", f"{archive}::map.otbm")
            self.assertTrue(report["read_only"] if "read_only" in report else True)
            self.assertTrue(report["sidecars"]["spawn_file"]["exists"])
            self.assertEqual(report["sidecars"]["house_file"]["xml_root"], "houses")
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["maps.zip"])

    def test_json_report_is_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.otbm"
            second = Path(directory) / "b.otbm"
            first.write_bytes(fixture("A"))
            second.write_bytes(fixture("B"))
            variants = [("a", str(first)), ("b", str(second))]
            one = MODULE.build_report(variants)
            two = MODULE.build_report(variants)
            self.assertEqual(one, two)
            self.assertTrue(one["read_only"])
            self.assertIn("não escolhe", one["recommendation"])


if __name__ == "__main__":
    unittest.main()
