from __future__ import annotations

from pathlib import Path
import csv
import struct
import tempfile
import unittest

from nwoassets.effect_importer import read_effect_manifest
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


class EffectManifestTests(unittest.TestCase):
    def test_reads_preserve_target_and_animation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "effect.png"
            write_png_rgba(image, PngImage(32, 64, bytes((1, 2, 3, 255)) * 2048))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "effect_id",
                        "source_path",
                        "frames",
                        "frame_duration_ms",
                        "animation_async",
                        "preserve_as",
                    )
                )
                writer.writerow((1, 1365, "effect.png", 2, 100, 1, 1469))
            entries = read_effect_manifest(manifest)
        self.assertEqual(entries[0].effect_id, 1365)
        self.assertEqual(entries[0].preserve_as, 1469)
        self.assertTrue(entries[0].animation_async)


class EffectDatTests(unittest.TestCase):
    def test_replaces_sparse_multitile_effect_only(self) -> None:
        item = b"\xFF" + empty_appearance()
        outfit = b"\xFF\x01\x00" + empty_appearance()
        source_bytes = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        replacement = encode_item_appearance(
            2,
            2,
            2,
            (0, 41, 42, 0, 43, 0, 0, 44),
            OTFI,
            frame_duration_ms=100,
            exact_size=32,
            allow_zero_sprite_ids=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(source_bytes)
            write_dat_appearances(source, output, OTFI, "effects", {1: replacement})
            spans = scan_dat_record_spans(output.read_bytes(), OTFI, str(output))
        effect = next(span for span in spans if span.category == "effects")
        self.assertEqual(effect.appearances[0].exact_size, 32)
        self.assertEqual(effect.appearances[0].sprite_ids, (0, 41, 42, 0, 43, 0, 0, 44))


if __name__ == "__main__":
    unittest.main()
