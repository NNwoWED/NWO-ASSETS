from __future__ import annotations

from pathlib import Path
import csv
import struct
import tempfile
import unittest

from nwoassets.effect_importer import read_effect_manifest
from nwoassets.errors import FormatError
from nwoassets.otfi import OtfiConfig
from nwoassets.png import PngImage, write_png_rgba
from nwoassets.roundtrip import (
    encode_item_appearance,
    scan_dat_record_spans,
    write_dat_appearances,
    write_dat_animation_durations,
    read_dat_animation_timings,
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
    def test_edits_loop_count_without_changing_pixels_or_other_records(self) -> None:
        item = b"\xFF" + empty_appearance()
        outfit = b"\xFF\x01\x00" + empty_appearance()
        appearance = encode_item_appearance(1, 1, 2, (1, 2), OTFI, frame_duration_ms=50)
        original = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + b"\xFF" + appearance + item
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.dat"
            destination = Path(directory) / "edited.dat"
            source.write_bytes(original)
            write_dat_animation_durations(source, destination, OTFI, "effects", {1: (50, 50)}, loop_count=1)
            edited = destination.read_bytes()
            timing = read_dat_animation_timings(edited, OTFI, "effects", {1}, "edited")[1]
            self.assertEqual(timing.loop_count, 1)
            self.assertEqual(timing.durations, ((50, 50), (50, 50)))
            self.assertEqual(sum(a != b for a, b in zip(original, edited)), 1)

    def test_appends_effects_and_preserves_existing_categories(self) -> None:
        item = b"\xFF" + empty_appearance()
        outfit = b"\xFF\x01\x00" + empty_appearance()
        source_bytes = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        effect = b"\x18" + struct.pack("<HH", 24, 24) + b"\xFF" + empty_appearance()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.dat"
            destination = Path(directory) / "appended.dat"
            source.write_bytes(source_bytes)
            write_dat_appearances(source, destination, OTFI, "effects", {}, new_records={2: effect})
            actual = destination.read_bytes()
            before = scan_dat_record_spans(source_bytes, OTFI, "before")
            after = {(span.category, span.thing_id): span for span in scan_dat_record_spans(actual, OTFI, "after")}
            self.assertEqual(struct.unpack_from("<H", actual, 8)[0], 2)
            for span in before:
                matching = after[(span.category, span.thing_id)]
                self.assertEqual(source_bytes[span.start:span.end], actual[matching.start:matching.end])
            added = after[("effects", 2)]
            self.assertEqual(actual[added.start:added.end], effect)
            with self.assertRaises(FormatError):
                write_dat_appearances(source, Path(directory) / "gap.dat", OTFI, "effects", {}, new_records={3: effect})

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
