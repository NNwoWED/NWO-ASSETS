from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.otb import OtbNode
from nwoassets.otbm import inspect_position_file
from nwoassets.roundtrip import write_otb_document


class OtbmPositionTests(unittest.TestCase):
    def test_reads_inline_and_child_items_in_stack_order(self) -> None:
        tile = OtbNode(
            bytes((5, 158, 171, 9)) + struct.pack("<H", 103),
            [OtbNode(bytes((6,)) + struct.pack("<H", 22904) + bytes((4,)) + struct.pack("<H", 77), [])],
        )
        area = OtbNode(bytes((4,)) + struct.pack("<HHB", 768, 1024, 7), [tile])
        root = OtbNode(bytes((0,)) + bytes(16), [OtbNode(bytes((2,)), [area])])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.otbm"
            write_otb_document(0, root, path)
            report = inspect_position_file(path, 926, 1195, 7)
        self.assertTrue(report["found"])
        self.assertEqual([item["server_id"] for item in report["items"]], [103, 22904])
        self.assertEqual([item["stack_position"] for item in report["items"]], [1, 2])
        self.assertEqual(report["items"][1]["action_id"], 77)

    def test_reports_absent_coordinate_without_modifying_map(self) -> None:
        root = OtbNode(bytes((0,)) + bytes(16), [OtbNode(bytes((2,)), [])])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.otbm"
            write_otb_document(0, root, path)
            before = path.read_bytes()
            report = inspect_position_file(path, 1, 2, 3)
            after = path.read_bytes()
        self.assertFalse(report["found"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
