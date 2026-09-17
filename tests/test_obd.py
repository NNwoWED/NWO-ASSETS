from __future__ import annotations

import lzma
from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.errors import FormatError
from nwoassets.obd import (
    dat_properties_from_obd,
    encode_obd_appearance,
    make_obd_otb_node,
    read_obd_item,
)
from nwoassets.otfi import OtfiConfig
from nwoassets.properties import OTB_FLAG_VALUES


def _obd_bytes(
    *, pattern_x: int = 1, frames: int = 1, properties: bytes = b"\x01\x0d\x20\xff"
) -> bytes:
    header = struct.pack("<HHBI", 200, 860, 1, 9 + len(properties))
    appearance = bytearray((1, 1, 1, pattern_x, 1, 1, frames))
    if frames > 1:
        appearance.extend(struct.pack("<BiB", 0, 0, 0))
        for _ in range(frames):
            appearance.extend(struct.pack("<II", 150, 150))
    for sprite_id in range(1, pattern_x * frames + 1):
        appearance.extend(struct.pack("<I", sprite_id))
        appearance.extend(bytes((128, 10, 20, 30)) * 1024)
    return lzma.compress(header + properties + appearance, format=lzma.FORMAT_ALONE)


class ObdReaderTests(unittest.TestCase):
    def test_reads_patterns_frames_and_argb_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "item.obd"
            path.write_bytes(_obd_bytes(pattern_x=2, frames=3))
            item = read_obd_item(path)
        self.assertEqual(item.layout, (1, 1, 1, 2, 1, 1, 3))
        self.assertEqual(item.properties, b"\x01\x0d\x20\xff")
        self.assertEqual(dat_properties_from_obd(item), b"\x01\x0d\x1f\xff")
        self.assertEqual(item.durations, ((150, 150),) * 3)
        self.assertEqual(item.original_sprite_ids, (1, 2, 3, 4, 5, 6))
        self.assertEqual(item.rgba_tiles()[0][:4], bytes((10, 20, 30, 128)))
        profile = OtfiConfig(
            extended=True,
            transparency=True,
            frame_durations=True,
            frame_groups=True,
            metadata_file="Tibia.dat",
            sprites_file="Tibia.spr",
            sprite_size=32,
            sprite_data_size=4096,
        )
        appearance = encode_obd_appearance(item, (101, 102, 103, 104, 105, 106), profile)
        self.assertEqual(appearance[:7], bytes((1, 1, 1, 2, 1, 1, 3)))
        self.assertEqual(appearance[-24:], struct.pack("<IIIIII", 101, 102, 103, 104, 105, 106))
        node = make_obd_otb_node(
            item, server_id=10051, client_id=9132, sprite_hash=b"s" * 16
        )
        self.assertEqual(node.data[0], 0)
        self.assertTrue(struct.unpack_from("<I", node.data, 1)[0] & OTB_FLAG_VALUES["always_on_top"])
        self.assertFalse(struct.unpack_from("<I", node.data, 1)[0] & OTB_FLAG_VALUES["movable"])

    def test_ground_item_gets_ground_group_speed_and_walk_stack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ground.obd"
            path.write_bytes(_obd_bytes(properties=b"\x00\x78\x00\x0d\xff"))
            item = read_obd_item(path)
        node = make_obd_otb_node(
            item, server_id=10058, client_id=9139, sprite_hash=b"s" * 16
        )
        self.assertEqual(node.data[0], 1)
        self.assertTrue(struct.unpack_from("<I", node.data, 1)[0] & OTB_FLAG_VALUES["walk_stack"])
        self.assertIn(b"\x14\x02\x00\x78\x00", node.data)

    def test_rejects_truncated_sprite(self) -> None:
        raw = lzma.decompress(_obd_bytes(), format=lzma.FORMAT_ALONE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.obd"
            path.write_bytes(lzma.compress(raw[:-1], format=lzma.FORMAT_ALONE))
            with self.assertRaises(FormatError):
                read_obd_item(path)


if __name__ == "__main__":
    unittest.main()
