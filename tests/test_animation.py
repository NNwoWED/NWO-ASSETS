from __future__ import annotations

from pathlib import Path
import csv
import struct
import tempfile
import unittest

from nwoassets.animation import read_animation_manifest
from nwoassets.otfi import OtfiConfig
from nwoassets.roundtrip import (
    encode_item_appearance,
    read_dat_animation_timings,
    write_dat_animation_durations,
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


class AnimationManifestTests(unittest.TestCase):
    def test_reads_individual_frame_durations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "animation.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    ("sequence", "category", "client_id", "frame_durations_ms")
                )
                writer.writerow((1, "items", 13544, "100|100|700"))
            category, edits = read_animation_manifest(path)
        self.assertEqual(category, "items")
        self.assertEqual(edits, {13544: (100, 100, 700)})


class AnimationDatTests(unittest.TestCase):
    def test_changes_only_frame_duration_pairs(self) -> None:
        animated = encode_item_appearance(
            1,
            1,
            3,
            (41, 42, 43),
            OTFI,
            frame_duration_ms=150,
        )
        item = b"\xFF" + animated
        outfit = b"\xFF\x01\x00" + empty_appearance()
        source_data = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(source_data)
            changes = write_dat_animation_durations(
                source, output, OTFI, "items", {100: (100, 100, 700)}
            )
            output_data = output.read_bytes()
        timings = read_dat_animation_timings(
            output_data, OTFI, "items", {100}, "output.dat"
        )
        self.assertEqual(
            timings[100].durations,
            ((100, 100), (100, 100), (700, 700)),
        )
        self.assertEqual(changes[100]["before"], ((150, 150),) * 3)
        self.assertEqual(len(source_data), len(output_data))


if __name__ == "__main__":
    unittest.main()
