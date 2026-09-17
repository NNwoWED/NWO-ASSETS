from __future__ import annotations

from pathlib import Path
import csv
import tempfile
import unittest

from nwoassets.exporter import compose_appearance_sheet
from nwoassets.otfi import OtfiConfig
from nwoassets.outfit_importer import (
    read_outfit_manifest,
    replace_outfit_sprite_ids,
    split_outfit_sheet,
)
from nwoassets.png import PngImage, write_png_rgba
from nwoassets.roundtrip import DatAppearance, scan_dat_record_spans


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


if __name__ == "__main__":
    unittest.main()
