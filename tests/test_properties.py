from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.otb import OtbNode
from nwoassets.otfi import OtfiConfig
from nwoassets.properties import read_otb_items, write_otb_item_flags
from nwoassets.roundtrip import (
    dat_item_flags,
    write_dat_item_flags,
    write_otb_document,
)


OTFI = OtfiConfig(
    extended=True, transparency=True, frame_durations=True, frame_groups=True,
    metadata_file="Tibia.dat", sprites_file="Tibia.spr", sprite_size=32,
    sprite_data_size=4096,
)


def _appearance() -> bytes:
    return b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"


class DatPropertyTests(unittest.TestCase):
    def test_edits_only_boolean_flags_and_preserves_payload_and_appearance(self) -> None:
        item = b"\x00\x96\x00\x02\x0D\xFF" + _appearance()
        plain = b"\xFF" + _appearance()
        outfit = b"\xFF\x01\x00" + _appearance()
        original = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + plain + plain
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(original)
            changes = write_dat_item_flags(source, output, OTFI, {100: ({0x0C}, {0x0D})})
            flags = dat_item_flags(output.read_bytes(), OTFI, str(output))
            rewritten = output.read_bytes()
        self.assertEqual(changes[100]["before"], (0x00, 0x02, 0x0D))
        self.assertEqual(flags[100], (0x00, 0x02, 0x0C))
        self.assertIn(b"\x00\x96\x00", rewritten)
        self.assertTrue(rewritten.endswith(outfit + plain + plain))


class OtbPropertyTests(unittest.TestCase):
    def test_edits_server_node_flags_without_changing_mapping(self) -> None:
        attributes = (
            b"\x10\x02\x00" + struct.pack("<H", 22019)
            + b"\x11\x02\x00" + struct.pack("<H", 21134)
        )
        root_node = OtbNode(b"root", [OtbNode(b"\0" + struct.pack("<I", 0x2002) + attributes, [])])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.otb"
            output = root / "output.otb"
            write_otb_document(0, root_node, source)
            changes = write_otb_item_flags(source, output, {22019: (1, 0)})
            items = read_otb_items(output)
        self.assertEqual(changes[22019], {"before": 0x2002, "after": 0x2003})
        self.assertEqual(items[22019]["client_id"], 21134)
        self.assertEqual(items[22019]["flags"], 0x2003)


if __name__ == "__main__":
    unittest.main()
