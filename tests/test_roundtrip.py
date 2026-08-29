from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.client import inspect_spr
from nwoassets.errors import FormatError
from nwoassets.otfi import OtfiConfig
from nwoassets.roundtrip import (
    append_spr_blocks,
    scan_dat_record_spans,
    write_otb_roundtrip,
    write_otbm_roundtrip,
)


OTFI = OtfiConfig(
    extended=True,
    transparency=True,
    frame_durations=True,
    frame_groups=True,
    metadata_file="Tibia.dat",
    sprites_file="Tibia.spr",
    sprite_size=32,
    sprite_data_size=4096,
)
TRANSPARENT_BLOCK = b"\xFF\x00\xFF\x04\x00\x00\x04\x00\x00"


def empty_appearance() -> bytes:
    return b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"


class DatRoundtripTests(unittest.TestCase):
    def test_scans_all_category_records_without_gaps(self) -> None:
        item = b"\xFF" + empty_appearance()
        outfit = b"\xFF\x01\x00" + empty_appearance()
        data = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        spans = scan_dat_record_spans(data, OTFI, "fixture.dat")
        self.assertEqual(
            [(span.category, span.thing_id) for span in spans],
            [("items", 100), ("outfits", 1), ("effects", 1), ("missiles", 1)],
        )
        rebuilt = data[:12] + b"".join(data[span.start : span.end] for span in spans)
        self.assertEqual(rebuilt, data)


class SprWriterTests(unittest.TestCase):
    def test_noop_is_byte_exact_and_append_preserves_old_block(self) -> None:
        source_bytes = struct.pack("<III", 1, 1, 12) + TRANSPARENT_BLOCK
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.spr"
            clone = root / "clone.spr"
            appended = root / "appended.spr"
            source.write_bytes(source_bytes)

            append_spr_blocks(source, clone, OTFI, ())
            append_spr_blocks(source, appended, OTFI, (TRANSPARENT_BLOCK,))

            self.assertEqual(clone.read_bytes(), source_bytes)
            report = inspect_spr(appended, OTFI, deep=True)
            self.assertEqual(report["sprite_count"], 2)
            self.assertEqual(report["zero_offsets"], 0)
            self.assertTrue(report["deep_validation"]["passed"])
            self.assertEqual(appended.read_bytes()[16:25], TRANSPARENT_BLOCK)

    def test_refuses_to_overwrite_source(self) -> None:
        source_bytes = struct.pack("<III", 1, 1, 12) + TRANSPARENT_BLOCK
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.spr"
            source.write_bytes(source_bytes)
            with self.assertRaises(FormatError):
                append_spr_blocks(source, source, OTFI, ())
            self.assertEqual(source.read_bytes(), source_bytes)


class TreeRoundtripTests(unittest.TestCase):
    def test_otb_roundtrip_preserves_escaped_bytes(self) -> None:
        tree = b"\xFE\x01\xFD\xFD\xFD\xFE\xFD\xFF\xFF"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.otb"
            output = root / "output.otb"
            source.write_bytes(struct.pack("<I", 0) + tree)
            write_otb_roundtrip(source, output)
            self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_otbm_roundtrip_preserves_stream(self) -> None:
        tree = b"\xFE\x00\xFD\xFD\xFE\x01\xFD\xFE\xFF\xFF"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.otbm"
            output = root / "output.otbm"
            source.write_bytes(struct.pack("<I", 0) + tree)
            write_otbm_roundtrip(source, output)
            self.assertEqual(output.read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
