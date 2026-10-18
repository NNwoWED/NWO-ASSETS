from __future__ import annotations

from pathlib import Path
import csv
import struct
import tempfile
import unittest

from nwoassets.exporter import compose_appearance_sheet
from nwoassets.otfi import OtfiConfig
from nwoassets.outfit_importer import (
    read_outfit_manifest,
    replace_outfit_sprite_ids,
    replace_outfit_sprite_ids_and_duration,
    replace_outfit_sprite_ids_and_frame_groups,
    replace_outfit_sprite_ids_and_frames,
    split_outfit_sheet,
)
from nwoassets.png import PngImage, write_png_rgba
from nwoassets.roundtrip import (
    DatAppearance,
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


def appearance(frames: int, sprite_ids: tuple[int, ...]) -> DatAppearance:
    return DatAppearance(2, 2, 32, 1, 4, 1, 1, frames, sprite_ids)


def encoded_group(frames: int, start_id: int, frame_group: int) -> bytes:
    count = 2 * 2 * 4 * frames
    output = bytearray((frame_group, 2, 2, 32, 1, 4, 1, 1, frames))
    if frames > 1:
        output.extend(b"\x01\x00\x00\x00\x00\x00")
        for _ in range(frames):
            output.extend((100).to_bytes(4, "little") * 2)
    for sprite_id in range(start_id, start_id + count):
        output.extend(sprite_id.to_bytes(4, "little"))
    return bytes(output)


class OutfitManifestTests(unittest.TestCase):
    def test_reads_target_and_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "outfit_id", "reference_outfit_id", "source_path"))
                writer.writerow((1, 92, 94, "outfit.png"))
            entries = read_outfit_manifest(manifest)
        self.assertEqual(entries[0].outfit_id, 92)
        self.assertEqual(entries[0].reference_outfit_id, 94)
        self.assertEqual(entries[0].operation, "reserved")

    def test_replace_allows_target_as_its_own_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                    )
                )
                writer.writerow((1, "replace", 324, 324, "outfit.png"))
            entries = read_outfit_manifest(manifest)
        self.assertEqual(entries[0].operation, "replace")
        self.assertEqual(entries[0].outfit_id, entries[0].reference_outfit_id)

    def test_replace_reads_frame_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                        "frames",
                        "frame_duration_ms",
                    )
                )
                writer.writerow((1, "replace", 324, 324, "outfit.png", 10, 100))
            entry = read_outfit_manifest(manifest)[0]
        self.assertEqual(entry.frames, 10)
        self.assertEqual(entry.frame_duration_ms, 100)

    def test_replace_reads_idle_and_walk_frame_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                        "frames_per_group",
                        "frame_duration_ms",
                    )
                )
                writer.writerow((1, "replace", 324, 324, "outfit.png", "1|2", 100))
            entry = read_outfit_manifest(manifest)[0]
        self.assertIsNone(entry.frames)
        self.assertEqual(entry.frames_per_group, (1, 2))
        self.assertEqual(entry.frame_duration_ms, 100)

    def test_replace_reads_different_duration_for_each_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                        "frames_per_group",
                        "frame_durations_per_group",
                    )
                )
                writer.writerow((1, "replace", 324, 324, "outfit.png", "8|8", "100|300"))
            entry = read_outfit_manifest(manifest)[0]
        self.assertEqual(entry.frames_per_group, (8, 8))
        self.assertEqual(entry.frame_durations_per_group, (100, 300))
        self.assertIsNone(entry.frame_duration_ms)

    def test_replace_reads_animate_always_dat_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                        "dat_add_flags",
                    )
                )
                writer.writerow((1, "replace", 324, 324, "outfit.png", "animate_always"))
            entry = read_outfit_manifest(manifest)[0]
        self.assertEqual(entry.dat_add_flags, (0x1B,))

    def test_reserved_reads_frame_override_from_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                        "frames",
                        "frame_duration_ms",
                    )
                )
                writer.writerow((1, "reserved", 92, 94, "outfit.png", 9, 100))
            entry = read_outfit_manifest(manifest)[0]
        self.assertEqual(entry.operation, "reserved")
        self.assertEqual(entry.outfit_id, 92)
        self.assertEqual(entry.reference_outfit_id, 94)
        self.assertEqual(entry.frames, 9)
        self.assertEqual(entry.frame_duration_ms, 100)

    def test_reserved_reads_duration_override_without_changing_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                        "frame_duration_ms",
                    )
                )
                writer.writerow((1, "reserved", 92, 94, "outfit.png", 100))
            entry = read_outfit_manifest(manifest)[0]
        self.assertIsNone(entry.frames)
        self.assertEqual(entry.frame_duration_ms, 100)

    def test_reserved_rejects_target_as_its_own_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                    )
                )
                writer.writerow((1, "reserved", 324, 324, "outfit.png"))
            with self.assertRaisesRegex(Exception, "operation=replace"):
                read_outfit_manifest(manifest)

    def test_rejects_unknown_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "outfit.png"
            write_png_rgba(image, PngImage(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    (
                        "sequence",
                        "operation",
                        "outfit_id",
                        "reference_outfit_id",
                        "source_path",
                    )
                )
                writer.writerow((1, "overwrite", 324, 324, "outfit.png"))
            with self.assertRaisesRegex(Exception, "reserved ou replace"):
                read_outfit_manifest(manifest)


class OutfitDatTests(unittest.TestCase):
    def test_adds_animate_always_without_changing_other_records(self) -> None:
        item_appearance = b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"
        outfit_appearance = b"\x01\x00" + item_appearance
        item = b"\xFF" + item_appearance
        outfit = b"\xFF" + outfit_appearance
        source_bytes = (
            struct.pack("<IHHHH", 1, 100, 1, 1, 1)
            + item
            + outfit
            + item
            + item
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(source_bytes)
            write_dat_appearances(
                source,
                output,
                OTFI,
                "outfits",
                {1: outfit_appearance},
                {1: {0x1B}},
            )
            rewritten = output.read_bytes()
            spans = scan_dat_record_spans(rewritten, OTFI, str(output))
        target = next(
            span for span in spans if span.category == "outfits" and span.thing_id == 1
        )
        self.assertEqual(rewritten[target.start : target.properties_end], b"\x1B\xFF")
        self.assertEqual(rewritten[target.properties_end : target.end], outfit_appearance)
        self.assertEqual(rewritten[-len(item) * 2 :], item * 2)


class OutfitSheetTests(unittest.TestCase):
    def test_split_inverts_export_layout_across_frame_groups(self) -> None:
        first = appearance(1, tuple(range(1, 17)))
        second = appearance(2, tuple(range(17, 49)))
        rgba_by_id = {
            sprite_id: bytes((sprite_id, 0, 0, 255)) * 1024
            for sprite_id in range(1, 49)
        }
        sheets = [
            compose_appearance_sheet(value, rgba_by_id)
            for value in (first, second)
        ]
        image = PngImage(
            sheets[0].width,
            sum(sheet.height for sheet in sheets),
            b"".join(sheet.rgba for sheet in sheets),
        )
        groups = split_outfit_sheet(image, (first, second), 32)
        self.assertEqual(groups[0], tuple(rgba_by_id[index] for index in range(1, 17)))
        self.assertEqual(groups[1], tuple(rgba_by_id[index] for index in range(17, 49)))

    def test_replaces_ids_but_preserves_group_metadata(self) -> None:
        first_ids = tuple(range(1, 17))
        second_ids = tuple(range(17, 49))
        template = b"\x02" + encoded_group(1, 1, 0) + encoded_group(2, 17, 1)
        replacement_ids = (
            tuple(range(101, 117)),
            tuple(range(201, 233)),
        )
        replacement = replace_outfit_sprite_ids(
            template,
            (appearance(1, first_ids), appearance(2, second_ids)),
            replacement_ids,
            OTFI,
        )
        self.assertEqual(replacement[:1], template[:1])
        self.assertNotEqual(replacement, template)

    def test_replaces_ids_and_duration_across_frame_groups(self) -> None:
        first_ids = tuple(range(1, 17))
        second_ids = tuple(range(17, 65))
        template = b"\x02" + encoded_group(1, 1, 0) + encoded_group(3, 17, 1)
        replacement_ids = (
            tuple(range(101, 117)),
            tuple(range(201, 249)),
        )
        replacement = replace_outfit_sprite_ids_and_duration(
            template,
            (appearance(1, first_ids), appearance(3, second_ids)),
            replacement_ids,
            75,
            OTFI,
        )
        second_group_start = 1 + len(encoded_group(1, 1, 0))
        first_duration = second_group_start + 9 + 6
        self.assertEqual(int.from_bytes(replacement[first_duration:first_duration + 4], "little"), 75)
        self.assertEqual(int.from_bytes(replacement[first_duration + 4:first_duration + 8], "little"), 75)

    def test_replaces_frame_count_and_duration(self) -> None:
        original_ids = tuple(range(1, 225))
        replacement_ids = tuple(range(1001, 1161))
        template = b"\x01" + encoded_group(14, 1, 1)
        replacement = replace_outfit_sprite_ids_and_frames(
            template,
            appearance(14, original_ids),
            appearance(10, replacement_ids),
            replacement_ids,
            100,
            OTFI,
        )
        self.assertEqual(replacement[0:2], b"\x01\x01")
        self.assertEqual(replacement[9], 10)
        self.assertEqual(int.from_bytes(replacement[16:20], "little"), 100)
        self.assertEqual(len(replacement), 10 + 6 + (10 * 8) + (160 * 4))

    def test_rebuilds_idle_and_walk_frame_groups(self) -> None:
        original_ids = tuple(range(1, 33))
        template = b"\x01" + encoded_group(2, 1, 0)
        idle_ids = tuple(range(101, 117))
        walk_ids = tuple(range(201, 233))
        replacement = replace_outfit_sprite_ids_and_frame_groups(
            template,
            (appearance(2, original_ids),),
            (appearance(1, idle_ids), appearance(2, walk_ids)),
            (idle_ids, walk_ids),
            (100, 300),
            OTFI,
        )
        self.assertEqual(replacement[0], 2)
        self.assertEqual(replacement[1], 0)
        self.assertEqual(replacement[9], 1)
        second_group_start = 10 + len(idle_ids) * 4
        self.assertEqual(replacement[second_group_start], 1)
        self.assertEqual(replacement[second_group_start + 8], 2)
        first_duration = second_group_start + 9 + 6
        self.assertEqual(
            int.from_bytes(replacement[first_duration:first_duration + 4], "little"),
            300,
        )


if __name__ == "__main__":
    unittest.main()
