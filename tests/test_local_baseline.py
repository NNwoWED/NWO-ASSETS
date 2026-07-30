from __future__ import annotations

from pathlib import Path
import unittest

from nwoassets.client import inspect_dat, inspect_spr, read_dat_header
from nwoassets.otb import inspect_otb
from nwoassets.otfi import parse_otfi


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / "860" / "Tibia.dat").is_file(), "baseline local ausente")
class LocalBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.otfi = parse_otfi(ROOT / "860" / "Tibia.otfi")

    def test_headers(self) -> None:
        dat = read_dat_header(ROOT / "860" / "Tibia.dat")
        spr = inspect_spr(ROOT / "860" / "Tibia.spr", self.otfi)
        self.assertEqual(dat["signature"], "0x4C2C7993")
        self.assertEqual(dat["max_item_id"], 24358)
        self.assertEqual(spr["signature"], "0x4C220594")
        self.assertEqual(spr["sprite_count"], 245380)
        self.assertEqual(spr["zero_offsets"], 0)

    def test_dat_parses_to_eof(self) -> None:
        report = inspect_dat(
            ROOT / "860" / "Tibia.dat",
            self.otfi,
            expected_metadata_reader=5,
            sprite_count=245380,
        )
        self.assertEqual(report["parsed_end_offset"], 4_349_631)
        self.assertEqual(report["total_records"], 30_123)
        self.assertEqual(report["flag_counts"]["custom_flag_22"], 4)

    def test_otb_version_and_range(self) -> None:
        report = inspect_otb(ROOT / "items" / "items.otb")
        self.assertEqual(report["version"]["csd"], "OTB 3.20.20-8.60")
        self.assertEqual(report["item_nodes"], 25_144)
        self.assertEqual(report["server_ids"]["min"], 100)
        self.assertEqual(report["server_ids"]["max"], 25_243)
        self.assertEqual(report["server_ids"]["gap_count"], 0)


if __name__ == "__main__":
    unittest.main()

