from __future__ import annotations

from pathlib import Path
import csv
import struct
import tempfile
import unittest

from nwoassets.missile_importer import read_missile_manifest
from nwoassets.otfi import OtfiConfig
from nwoassets.png import PngImage, write_png_rgba
from nwoassets.roundtrip import (
    encode_item_appearance,
    scan_dat_record_spans,
    write_dat_appearances,
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


def empty_appearance() -> bytes:
    return b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"


class MissileManifestTests(unittest.TestCase):
    def test_reads_reserved_directional_animation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "missile.png"
            write_png_rgba(image, PngImage(32, 64, bytes((1, 2, 3, 255)) * 2048))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "missile_id",
                        "reference_missile_id",
                        "source_path",
                        "frames",
                        "frame_duration_ms",
                        "animation_async",
                    )
                )
                writer.writerow((1, "reserved", 121, 217, "missile.png", 2, 100, 0))
            entries = read_missile_manifest(manifest)
        self.assertEqual(entries[0].missile_id, 121)
        self.assertEqual(entries[0].reference_missile_id, 217)
        self.assertEqual(entries[0].frames, 2)
        self.assertEqual(entries[0].frame_duration_ms, 100)


class MissileDatTests(unittest.TestCase):
    def test_encodes_directional_animated_missile_only(self) -> None:
        item = b"\xFF" + empty_appearance()
        outfit = b"\xFF\x01\x00" + empty_appearance()
        source_bytes = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        sprite_ids = tuple(range(1, 19))
        replacement = encode_item_appearance(
            1,
            1,
            2,
            sprite_ids,
            OTFI,
            frame_duration_ms=100,
            pattern_x=3,
            pattern_y=3,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(source_bytes)
            write_dat_appearances(source, output, OTFI, "missiles", {1: replacement})
            spans = scan_dat_record_spans(output.read_bytes(), OTFI, str(output))
        missile = next(span for span in spans if span.category == "missiles")
        appearance = missile.appearances[0]
        self.assertEqual((appearance.pattern_x, appearance.pattern_y), (3, 3))
        self.assertEqual(appearance.frames, 2)
        self.assertEqual(appearance.sprite_ids, sprite_ids)


if __name__ == "__main__":
    unittest.main()
