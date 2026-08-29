from __future__ import annotations

from pathlib import Path
import binascii
import csv
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from nwoassets.errors import FormatError
from nwoassets.importer import (
    _commit_transaction,
    _otb_sprite_hashes,
    read_manifest,
    update_otb_sprite_hashes,
    verify_sprite_hash_algorithm,
)
from nwoassets.otb import OtbNode
from nwoassets.otfi import OtfiConfig, parse_otfi
from nwoassets.png import normalize_rgba, read_png_rgba, split_tiles_bottom_right_first
from nwoassets.roundtrip import (
    encode_simple_item_appearance,
    scan_dat_record_spans,
    write_dat_item_appearances,
    write_otb_document,
)
from nwoassets.sprites import decode_sprite_rgba, encode_sprite_rgba, sprite_hash


ROOT = Path(__file__).resolve().parents[1]
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


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png_rgba(width: int, height: int, pixels: bytes) -> bytes:
    rows = b"".join(
        b"\0" + pixels[row * width * 4 : (row + 1) * width * 4]
        for row in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(rows)) + _chunk(b"IEND", b"")


def empty_appearance() -> bytes:
    return b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"


class PngPipelineTests(unittest.TestCase):
    def test_normalizes_and_splits_bottom_right_first(self) -> None:
        left = bytes((255, 0, 255, 255)) * 32
        right = bytes((0, 0, 255, 255)) * 32
        pixels = b"".join(left + right for _ in range(32))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "two-tiles.png"
            path.write_bytes(png_rgba(64, 32, pixels))
            image = normalize_rgba(read_png_rgba(path))
        tiles = split_tiles_bottom_right_first(image)
        self.assertEqual(len(tiles), 2)
        self.assertEqual(tiles[0][:4], bytes((0, 0, 255, 255)))
        self.assertEqual(tiles[1][:4], b"\0\0\0\0")


class SpriteCodecTests(unittest.TestCase):
    def test_rgba_rle_roundtrip(self) -> None:
        pixels = bytearray(32 * 32 * 4)
        pixels[0:4] = bytes((10, 20, 30, 128))
        pixels[-4:] = bytes((40, 50, 60, 255))
        encoded = encode_sprite_rgba(bytes(pixels))
        self.assertEqual(decode_sprite_rgba(encoded), bytes(pixels))

    def test_item_editor_transparent_hash_golden(self) -> None:
        calculated = sprite_hash([bytes(32 * 32 * 4)]).hex().upper()
        self.assertEqual(calculated, "4B1B1C88FF2FAF290EBC392B116D101C")


class DatImporterTests(unittest.TestCase):
    def test_replaces_only_target_item_appearance(self) -> None:
        item = b"\xFF" + empty_appearance()
        outfit = b"\xFF\x01\x00" + empty_appearance()
        source_bytes = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + item + item
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(source_bytes)
            appearance = encode_simple_item_appearance(1, 1, (42,), OTFI)
            write_dat_item_appearances(source, output, OTFI, {100: appearance})
            output_bytes = output.read_bytes()
            spans = scan_dat_record_spans(output_bytes, OTFI, str(output))
        self.assertEqual(spans[0].appearances[0].sprite_ids, (42,))
        self.assertEqual(output_bytes[-len(outfit + item + item) :], outfit + item + item)

    def test_multitile_exact_size_matches_object_builder(self) -> None:
        appearance = encode_simple_item_appearance(2, 2, (1, 2, 3, 4), OTFI)
        self.assertEqual(appearance[:3], b"\x02\x02\x40")


class OtbImporterTests(unittest.TestCase):
    def test_updates_hash_and_preserves_mapping(self) -> None:
        attributes = (
            b"\x10\x02\x00" + struct.pack("<H", 100)
            + b"\x11\x02\x00" + struct.pack("<H", 100)
            + b"\x20\x10\x00" + bytes(16)
        )
        root_node = OtbNode(b"root", [OtbNode(b"\0" + bytes(4) + attributes, [])])
        expected = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.otb"
            output = root / "output.otb"
            write_otb_document(0, root_node, source)
            updated = update_otb_sprite_hashes(source, output, {100: expected})
            hashes = _otb_sprite_hashes(output)
        self.assertEqual(updated, {100: 1})
        self.assertEqual(hashes[100], [expected])


class ManifestTests(unittest.TestCase):
    def test_reads_relative_manifest_in_declared_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "item.png"
            image.write_bytes(png_rgba(32, 32, bytes((1, 2, 3, 255)) * 1024))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "client_id", "source_path"))
                writer.writerow((1, 100, "item.png"))
            entries = read_manifest(manifest)
        self.assertEqual(entries[0].client_id, 100)
        self.assertEqual(entries[0].source_path, image.resolve())


class TransactionTests(unittest.TestCase):
    def _files(self, root: Path) -> dict[Path, Path]:
        originals = [root / name for name in ("Tibia.dat", "Tibia.spr", "items.otb")]
        replacements: dict[Path, Path] = {}
        for original in originals:
            original.write_bytes(b"original-" + original.name.encode())
            pending = original.with_name(f".{original.name}.pending")
            pending.write_bytes(b"new-" + original.name.encode())
            replacements[original] = pending
        return replacements

    def test_commits_all_prepared_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replacements = self._files(root)
            with patch(
                "nwoassets.importer.validate_root",
                return_value={"passed": True, "errors": [], "warnings": []},
            ):
                report = _commit_transaction(root, replacements, deep_spr=False)
            values = [path.read_bytes() for path in replacements]
        self.assertTrue(report["passed"])
        self.assertTrue(all(value.startswith(b"new-") for value in values))

    def test_restores_every_original_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replacements = self._files(root)
            expected = {path: path.read_bytes() for path in replacements}
            with patch(
                "nwoassets.importer.validate_root",
                return_value={"passed": False, "errors": ["forced"], "warnings": []},
            ):
                with self.assertRaises(FormatError):
                    _commit_transaction(root, replacements, deep_spr=False)
            values = {path: path.read_bytes() for path in replacements}
            leftovers = list(root.glob("*.nwoassets.*"))
        self.assertEqual(values, expected)
        self.assertEqual(leftovers, [])


@unittest.skipUnless((ROOT / "assets" / "860" / "Tibia.dat").is_file(), "baseline local ausente")
class LocalSpriteHashGateTests(unittest.TestCase):
    def test_matches_item_editor_hashes_across_baseline(self) -> None:
        otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")
        report = verify_sprite_hash_algorithm(
            ROOT / "assets" / "860" / "Tibia.dat",
            ROOT / "assets" / "860" / "Tibia.spr",
            ROOT / "assets" / "items" / "items.otb",
            otfi,
        )
        self.assertEqual(report["sample_count"], 64)
        self.assertTrue(report["passed"], report["mismatches"])


if __name__ == "__main__":
    unittest.main()
