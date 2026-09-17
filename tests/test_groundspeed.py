from __future__ import annotations

from pathlib import Path
import csv
import struct
import tempfile
import unittest

from nwoassets.groundspeed import (
    GroundSpeedEdit,
    read_dat_ground_speeds,
    read_ground_speed_manifest,
    read_otb_ground_speeds,
    write_dat_ground_speeds,
    write_otb_ground_speeds,
)
from nwoassets.otb import OtbNode
from nwoassets.otfi import OtfiConfig
from nwoassets.roundtrip import write_otb_document


OTFI = OtfiConfig(
    extended=True, transparency=True, frame_durations=True, frame_groups=True,
    metadata_file="Tibia.dat", sprites_file="Tibia.spr", sprite_size=32,
    sprite_data_size=4096,
)


def _appearance() -> bytes:
    return b"\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00"


class GroundSpeedManifestTests(unittest.TestCase):
    def test_reads_locked_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ground.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("sequence", "server_id", "client_id", "ground_speed"))
                writer.writerow((1, 500, 400, 100))
            entries = read_ground_speed_manifest(path)
        self.assertEqual(entries, [GroundSpeedEdit(1, 500, 400, 100)])


class DatGroundSpeedTests(unittest.TestCase):
    def test_changes_only_ground_payload(self) -> None:
        item = b"\x00\x96\x00\x15\x07\x00\x08\x00\x0D\xFF" + _appearance()
        plain = b"\xFF" + _appearance()
        outfit = b"\xFF\x01\x00" + _appearance()
        original = struct.pack("<IHHHH", 1, 100, 1, 1, 1) + item + outfit + plain + plain
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.dat"
            output = root / "output.dat"
            source.write_bytes(original)
            changes = write_dat_ground_speeds(source, output, OTFI, {100: 100})
            rewritten = output.read_bytes()
            speeds = read_dat_ground_speeds(rewritten, OTFI, str(output))
        self.assertEqual(changes[100], {"before": 150, "after": 100})
        self.assertEqual(speeds[100], 100)
        self.assertIn(b"\x00\x64\x00\x15\x07\x00\x08\x00\x0D\xFF", rewritten)
        self.assertTrue(rewritten.endswith(outfit + plain + plain))


class OtbGroundSpeedTests(unittest.TestCase):
    def test_changes_only_ground_attribute(self) -> None:
        attributes = (
            b"\x10\x02\x00" + struct.pack("<H", 500)
            + b"\x11\x02\x00" + struct.pack("<H", 400)
            + b"\x14\x02\x00" + struct.pack("<H", 150)
        )
        root_node = OtbNode(b"root", [OtbNode(b"\x01" + struct.pack("<I", 0x2002) + attributes, [])])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.otb"
            output = root / "output.otb"
            write_otb_document(0, root_node, source)
            changes = write_otb_ground_speeds(source, output, {500: 100})
            items = read_otb_ground_speeds(output)
        self.assertEqual(changes[500], {"before": 150, "after": 100})
        self.assertEqual(items[500]["client_id"], 400)
        self.assertEqual(items[500]["ground_speed"], 100)
        self.assertEqual(items[500]["flags"], 0x2002)


if __name__ == "__main__":
    unittest.main()
