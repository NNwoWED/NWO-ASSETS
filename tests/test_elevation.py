from __future__ import annotations

import csv
from pathlib import Path
import struct
import tempfile
import unittest

from nwoassets.elevation import (
    ElevationEdit,
    read_dat_elevations,
    read_elevation_manifest,
    write_dat_elevations,
)
from nwoassets.otfi import OtfiConfig


OTFI = OtfiConfig(
    extended=True, transparency=True, frame_durations=True, frame_groups=True,
    metadata_file="Tibia.dat", sprites_file="Tibia.spr", sprite_size=32,
    sprite_data_size=4096,
)


def _appearance() -> bytes:
    return b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"


class ElevationTests(unittest.TestCase):
    def test_reads_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "elevation.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "server_id", "client_id", "elevation"))
                writer.writerow((1, 16543, 15658, 8))
            self.assertEqual(
                read_elevation_manifest(path),
                [ElevationEdit(1, 16543, 15658, 8)],
            )

    def test_changes_only_elevation_payload(self) -> None:
        item = b"\x19\x0F\x00\x10\xFF" + _appearance()
        plain = b"\xFF" + _appearance()
        outfit = b"\xFF\x01\x00" + _appearance()
        original = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + plain + plain
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(original)
            changes = write_dat_elevations(source, output, OTFI, {100: 8})
            rewritten = output.read_bytes()
            values = read_dat_elevations(rewritten, OTFI, str(output))
        self.assertEqual(changes[100], {"before": 15, "after": 8})
        self.assertEqual(values[100], 8)
        self.assertIn(b"\x19\x08\x00\x10\xFF", rewritten)
        self.assertTrue(rewritten.endswith(outfit + plain + plain))


if __name__ == "__main__":
    unittest.main()
