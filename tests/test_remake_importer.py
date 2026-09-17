from __future__ import annotations

import lzma
from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.obd import (
    dat_properties_from_obd,
    encode_obd_appearance,
    read_obd_item,
)
from nwoassets.otb import OtbNode, parse_otb_tree
from nwoassets.otfi import OtfiConfig
from nwoassets.remake_importer import (
    _write_dat_remake_records,
    _write_otb_remake_nodes,
)
from nwoassets.roundtrip import scan_dat_record_spans, write_otb_document


PROFILE = OtfiConfig(
    extended=True,
    transparency=True,
    frame_durations=True,
    frame_groups=True,
    metadata_file="Tibia.dat",
    sprites_file="Tibia.spr",
    sprite_size=32,
    sprite_data_size=4096,
)


def _fixture_obd(path: Path) -> None:
    properties = b"\x00\x78\x00\x0d\xff"
    header = struct.pack("<HHBI", 200, 860, 1, 9 + len(properties))
    appearance = bytes((1, 1, 1, 2, 1, 1, 1))
    tile = bytes((255, 10, 20, 30)) * 1024
    payload = (
        header + properties + appearance
        + struct.pack("<I", 1) + tile
        + struct.pack("<I", 2) + tile
    )
    path.write_bytes(lzma.compress(payload, format=lzma.FORMAT_ALONE))


class RemakeWriterTests(unittest.TestCase):
    def test_dat_and_otb_writers_preserve_unrelated_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            obd_path = root / "item.obd"
            _fixture_obd(obd_path)
            item = read_obd_item(obd_path)
            appearance = encode_obd_appearance(item, (500, 501), PROFILE)
            props = dat_properties_from_obd(item)

            empty = bytes((1, 1, 1, 1, 1, 1, 1)) + struct.pack("<I", 1)
            source_dat = root / "source.dat"
            pending_dat = root / "pending.dat"
            source_dat.write_bytes(
                struct.pack("<IHHHH", 1, 100, 1, 1, 1)
                + b"\xff" + empty
                + b"\xff\x01\x00" + empty
                + b"\xff" + empty
                + b"\xff" + empty
            )
            _write_dat_remake_records(
                source_dat, pending_dat, PROFILE, {100: (props, appearance)}
            )
            spans = scan_dat_record_spans(pending_dat.read_bytes(), PROFILE, "pending")
            self.assertEqual(spans[0].appearances[0].pattern_x, 2)
            self.assertEqual(spans[0].appearances[0].sprite_ids, (500, 501))
            self.assertEqual(
                pending_dat.read_bytes()[spans[0].start:spans[0].properties_end], props
            )

            attributes = (
                b"\x10\x02\x00" + struct.pack("<H", 200)
                + b"\x11\x02\x00" + struct.pack("<H", 100)
                + b"\x20\x10\x00" + bytes(16)
            )
            source_otb = root / "source.otb"
            pending_otb = root / "pending.otb"
            write_otb_document(
                0, OtbNode(b"root", [OtbNode(b"\0" + bytes(4) + attributes, [])]),
                source_otb,
            )
            _write_otb_remake_nodes(
                source_otb, pending_otb, {200: (100, item, b"h" * 16)}
            )
            _, written = parse_otb_tree(pending_otb)
            self.assertEqual(written.children[0].data[0], 1)
            self.assertIn(b"\x14\x02\x00\x78\x00", written.children[0].data)


if __name__ == "__main__":
    unittest.main()
