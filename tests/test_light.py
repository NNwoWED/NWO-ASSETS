from __future__ import annotations

import csv
from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.light import (
    LightEdit,
    read_dat_lights,
    read_light_manifest,
    write_dat_light_colors,
)
from nwoassets.otfi import OtfiConfig


OTFI = OtfiConfig(
    extended=True, transparency=True, frame_durations=True, frame_groups=True,
    metadata_file="Tibia.dat", sprites_file="Tibia.spr", sprite_size=32,
    sprite_data_size=4096,
)


def _appearance() -> bytes:
    return b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"


class LightTests(unittest.TestCase):
    def test_reads_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "light.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "server_id", "client_id", "light_color"))
                writer.writerow((1, 27224, 26339, 210))
            self.assertEqual(
                read_light_manifest(path),
                [LightEdit(1, 27224, 26339, 210)],
            )

    def test_changes_only_light_color_and_preserves_intensity(self) -> None:
        item = b"\x15\x05\x00\x1E\x00\x10\xFF" + _appearance()
        plain = b"\xFF" + _appearance()
        outfit = b"\xFF\x01\x00" + _appearance()
        original = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + plain + plain
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(original)
            changes = write_dat_light_colors(source, output, OTFI, {100: 210})
            rewritten = output.read_bytes()
            values = read_dat_lights(rewritten, OTFI, str(output))
        self.assertEqual(
            changes[100],
            {"intensity": 5, "before_color": 30, "after_color": 210},
        )
        self.assertEqual(values[100], (5, 210))
        self.assertIn(b"\x15\x05\x00\xD2\x00\x10\xFF", rewritten)
        self.assertTrue(rewritten.endswith(outfit + plain + plain))


if __name__ == "__main__":
    unittest.main()
