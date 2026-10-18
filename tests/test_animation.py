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

    def test_accepts_outfits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "animation.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    ("sequence", "category", "client_id", "frame_durations_ms")
                )
                writer.writerow((1, "outfits", 1026, "75|75|75"))
            category, edits = read_animation_manifest(path)
        self.assertEqual(category, "outfits")
        self.assertEqual(edits, {1026: (75, 75, 75)})


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

    def test_changes_only_animated_outfit_group_durations(self) -> None:
        static_group = b"\x00" + empty_appearance()
        animated_group = b"\x01" + encode_item_appearance(
            1,
            1,
            3,
            (51, 52, 53),
            OTFI,
            frame_duration_ms=100,
        )
        item = b"\xFF" + empty_appearance()
        outfit = b"\xFF\x02" + static_group + animated_group
        source_data = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(source_data)
            changes = write_dat_animation_durations(
                source, output, OTFI, "outfits", {1: (75, 75, 75)}
            )
            output_data = output.read_bytes()
        timings = read_dat_animation_timings(
            output_data, OTFI, "outfits", {1}, "output.dat"
        )
        self.assertEqual(timings[1].durations, ((75, 75),) * 3)
        self.assertEqual(changes[1]["before"], ((100, 100),) * 3)
        self.assertEqual(len(source_data), len(output_data))
        differing = [
            index
            for index, (before, after) in enumerate(zip(source_data, output_data))
            if before != after
        ]
        self.assertEqual(len(differing), 6)


if __name__ == "__main__":
    unittest.main()
