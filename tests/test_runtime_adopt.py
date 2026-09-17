from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.errors import FormatError
from nwoassets.otb import OtbNode, parse_otb_tree
from nwoassets.roundtrip import write_otb_document
from nwoassets.runtime_adopt import _parse_attributes, update_otb_from_runtime


def item_node(server_id: int, client_id: int, flags: int = 0xE0) -> OtbNode:
    attributes = (
        b"\x10\x02\x00" + struct.pack("<H", server_id)
        + b"\x11\x02\x00" + struct.pack("<H", client_id)
        + b"\x20\x10\x00" + bytes(16)
    )
    return OtbNode(b"\0" + struct.pack("<I", flags) + attributes, [])


class RuntimeAdoptOtbTests(unittest.TestCase):
    def test_updates_hash_flags_minimap_and_stack_order(self) -> None:
        expected_hash = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.otb"
            output = Path(directory) / "output.otb"
            write_otb_document(0, OtbNode(b"root", [item_node(14571, 13694)]), source)
            report = update_otb_from_runtime(
                source,
                output,
                sprite_hashes={13694: expected_hash},
                property_changes={
                    13694: (
                        {0x05: b"", 0x10: b""},
                        {0x02: b"", 0x0C: b"", 0x0D: b"", 0x1C: b"\x0c\x00"},
                    )
                },
                animated={13694: False},
            )
            _, root = parse_otb_tree(output)
        node = root.children[0]
        self.assertEqual(struct.unpack_from("<I", node.data, 1)[0], 0x2001)
        attributes = dict(_parse_attributes(node.data, "test"))
        self.assertEqual(attributes[0x20], expected_hash)
        self.assertEqual(attributes[0x21], b"\x0c\x00")
        self.assertEqual(attributes[0x2B], b"\x02")
        self.assertEqual(report[0]["server_id"], 14571)

    def test_rejects_changed_payload_without_safe_otb_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.otb"
            output = Path(directory) / "output.otb"
            write_otb_document(0, OtbNode(b"root", [item_node(100, 200)]), source)
            with self.assertRaisesRegex(FormatError, "sem equivalencia"):
                update_otb_from_runtime(
                    source,
                    output,
                    sprite_hashes={},
                    property_changes={200: ({}, {0x15: b"\0\0\0\0"})},
                    animated={},
                )


if __name__ == "__main__":
    unittest.main()
