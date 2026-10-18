from pathlib import Path
import csv
import struct
import tempfile
import unittest

from nwoassets.clone_item_importer import (
    CloneItemEntry,
    clone_otb_node,
    read_clone_item_manifest,
    split_frame_grid,
    write_dat_with_clones,
)
from nwoassets.otb import OtbNode
from nwoassets.otfi import OtfiConfig
from nwoassets.png import PngImage, write_png_rgba


OTFI = OtfiConfig(True, True, True, True, "Tibia.dat", "Tibia.spr", 32, 4096)


class CloneItemImporterTests(unittest.TestCase):
    def test_grid_is_split_left_to_right_then_top_to_bottom(self):
        colors = [bytes((red, 0, 0, 255)) * (32 * 32) for red in (1, 2, 3, 4)]
        rgba = bytearray(64 * 64 * 4)
        for index, tile in enumerate(colors):
            x = (index % 2) * 32
            y = (index // 2) * 32
            for row in range(32):
                start = ((y + row) * 64 + x) * 4
                rgba[start:start + 32 * 4] = tile[row * 32 * 4:(row + 1) * 32 * 4]
        frames = split_frame_grid(PngImage(64, 64, bytes(rgba)), 32, 32, 4)
        self.assertEqual([frame[0][0] for frame in frames], [1, 2, 3, 4])

    def test_manifest_locks_source_and_new_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = root / "item_100.png"
            write_png_rgba(png, PngImage(32, 32, bytes(32 * 32 * 4)))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "source_server_id", "target_server_id", "target_client_id", "source_path", "frame_width", "frame_height", "frames", "frame_duration_ms", "animation_async"))
                writer.writerow((1, 100, 200, 150, png.name, 32, 32, 1, "", 0))
            entries = read_clone_item_manifest(manifest)
        self.assertEqual(entries[0], CloneItemEntry(1, 100, 200, 150, png.resolve(), 32, 32, 1, None, False))

    def test_manifest_accepts_explicit_patterns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = root / "item_100.png"
            write_png_rgba(png, PngImage(64, 64, bytes(64 * 64 * 4)))
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "source_server_id", "target_server_id", "target_client_id", "source_path", "frame_width", "frame_height", "frames", "frame_duration_ms", "animation_async", "layers", "pattern_x", "pattern_y", "pattern_z"))
                writer.writerow((1, 100, 200, 150, png.name, 32, 32, 1, "", 0, 1, 2, 2, 1))
            entry = read_clone_item_manifest(manifest)[0]
        self.assertEqual((entry.pattern_x, entry.pattern_y, entry.frames), (2, 2, 1))

    def test_manifest_accepts_repeated_source_for_distinct_clones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.png"
            second = root / "second.png"
            image = PngImage(32, 32, bytes(32 * 32 * 4))
            write_png_rgba(first, image)
            write_png_rgba(second, image)
            manifest = root / "manifest.csv"
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "source_server_id", "target_server_id", "target_client_id", "source_path", "frame_width", "frame_height", "frames", "frame_duration_ms", "animation_async"))
                writer.writerow((1, 100, 200, 150, first.name, 32, 32, 1, "", 0))
                writer.writerow((2, 100, 201, 151, second.name, 32, 32, 1, "", 0))
            entries = read_clone_item_manifest(manifest)
        self.assertEqual([entry.source_server_id for entry in entries], [100, 100])
        self.assertEqual([entry.target_server_id for entry in entries], [200, 201])

    def test_cloned_otb_node_changes_only_ids_hash_and_animation(self):
        digest = bytes(range(16))
        data = bytearray(b"\0" + struct.pack("<I", 1 << 24))
        for attribute, payload in ((0x10, struct.pack("<H", 100)), (0x11, struct.pack("<H", 90)), (0x20, b"x" * 16), (0x21, b"\x07\0")):
            data.extend(bytes((attribute,)) + struct.pack("<H", len(payload)) + payload)
        cloned = clone_otb_node(OtbNode(bytes(data), []), server_id=200, client_id=190, digest=digest, animated=False)
        self.assertEqual(struct.unpack_from("<I", cloned.data, 1)[0] & (1 << 24), 0)
        self.assertIn(struct.pack("<H", 200), cloned.data)
        self.assertIn(struct.pack("<H", 190), cloned.data)
        self.assertIn(digest, cloned.data)
        self.assertIn(b"\x21\x02\0\x07\0", cloned.data)

    def test_dat_writer_appends_item_before_outfits(self):
        appearance = b"\x01\x01\x01\x01\x01\x01\x01" + struct.pack("<I", 1)
        item = b"\xFF" + appearance
        outfit = b"\xFF\x01\0" + appearance
        plain = b"\xFF" + appearance
        original = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + plain + plain
        record = b"\x0D\xFF" + appearance
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            target = root / "target.dat"
            source.write_bytes(original)
            write_dat_with_clones(source, target, OTFI, [record])
            written = target.read_bytes()
        self.assertEqual(struct.unpack_from("<H", written, 4)[0], 101)
        self.assertIn(item + record + outfit, written)


if __name__ == "__main__":
    unittest.main()
