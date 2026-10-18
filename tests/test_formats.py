from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.binary import BinaryReader
from nwoassets.client import inspect_dat
from nwoassets.errors import FormatError, ProfileError
from nwoassets.otfi import OtfiConfig, parse_otfi
from nwoassets.profiles import TIBIA_860_V2, detect_profile


class BinaryReaderTests(unittest.TestCase):
    def test_little_endian_and_bounds(self) -> None:
        reader = BinaryReader(b"\x34\x12\x78\x56\x34\x12")
        self.assertEqual(reader.u16(), 0x1234)
        self.assertEqual(reader.u32(), 0x12345678)
        with self.assertRaises(FormatError):
            reader.u8()


class ProfileTests(unittest.TestCase):
    def test_detects_local_profile(self) -> None:
        profile = detect_profile(0x4C2C7993, 0x4C220594)
        self.assertEqual(profile, TIBIA_860_V2)
        self.assertEqual(profile.metadata_reader, 5)

    def test_rejects_mixed_signatures(self) -> None:
        with self.assertRaises(ProfileError):
            detect_profile(0x4C2C7993, 0x53835077)


class OtfiTests(unittest.TestCase):
    def test_parses_features(self) -> None:
        content = """DatSpr
  extended: true
  transparency: true
  frame-durations: true
  frame-groups: true
  metadata-file: Tibia.dat
  sprites-file: Tibia.spr
  sprite-size: 32
  sprite-data-size: 4096
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Tibia.otfi"
            path.write_text(content, encoding="utf-8")
            config = parse_otfi(path)
        self.assertTrue(config.extended)
        self.assertTrue(config.transparency)
        self.assertEqual(config.sprite_size, 32)
        self.assertEqual(config.sprite_data_size, 4096)


class DatSpriteLimitTests(unittest.TestCase):
    def test_counts_sprites_across_all_frame_groups(self) -> None:
        otfi = OtfiConfig(
            extended=True,
            transparency=True,
            frame_durations=True,
            frame_groups=True,
            metadata_file="Tibia.dat",
            sprites_file="Tibia.spr",
            sprite_size=32,
            sprite_data_size=3,
        )
        single = b"\x01\x01\x01\x01\x01\x01\x01" + struct.pack("<I", 1)
        double = b"\x01\x01\x01\x02\x01\x01\x01" + struct.pack("<II", 1, 2)
        item = b"\xFF" + single
        outfit = b"\xFF\x02\x00" + double + b"\x01" + double
        data = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Tibia.dat"
            path.write_bytes(data)
            with self.assertRaisesRegex(FormatError, "4 sprites entre todos os frame groups"):
                inspect_dat(
                    path,
                    otfi,
                    expected_metadata_reader=5,
                    sprite_count=2,
                )


if __name__ == "__main__":
    unittest.main()

