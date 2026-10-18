from __future__ import annotations

from pathlib import Path
import unittest

from nwoassets.client import inspect_dat, inspect_spr, read_dat_header
from nwoassets.content import sha256_file
from nwoassets.otb import inspect_otb
from nwoassets.otfi import parse_otfi


ROOT = Path(__file__).resolve().parents[1]

BASELINE_SHA256 = {
    "assets/860/Tibia.dat": "629EB604EB0194BF77872F47061D1FCB4EF9F6C0785A26FBE24AA4C9811ABD71",
    "assets/860/Tibia.spr": "232D4B0E19995307FFAB96875EF4DD97C3394E7A01E45599AF3BFDDF75588F7B",
    "assets/860/Tibia.otfi": "7743548835944BC799CB871A4E5DEF84F7AF76815031871B9CE74B5EC0E8ADD3",
    "assets/items/items.otb": "5AA04C31E388F3B995DFACE5BAC7AB4BA0C007FC96B6953DB2D4F5AB140457E3",
    "assets/world/mapanovo.otbm": "8CDFDDF9DC2A9E53053E4F3FAF7F6825FD89B6B63EE06272ECD234B387202821",
}


@unittest.skipUnless((ROOT / "assets" / "860" / "Tibia.dat").is_file(), "baseline local ausente")
class LocalBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.otfi = parse_otfi(ROOT / "assets" / "860" / "Tibia.otfi")

    def test_headers(self) -> None:
        dat = read_dat_header(ROOT / "assets" / "860" / "Tibia.dat")
        spr = inspect_spr(ROOT / "assets" / "860" / "Tibia.spr", self.otfi)
        self.assertEqual(dat["signature"], "0x4C2C7993")
        self.assertEqual(dat["max_item_id"], 24715)
        self.assertEqual(spr["signature"], "0x4C220594")
        self.assertEqual(spr["sprite_count"], 276726)
        self.assertEqual(spr["zero_offsets"], 0)

    def test_dat_parses_to_eof(self) -> None:
        report = inspect_dat(
            ROOT / "assets" / "860" / "Tibia.dat",
            self.otfi,
            expected_metadata_reader=5,
            sprite_count=276726,
        )
        self.assertEqual(report["parsed_end_offset"], 4_510_591)
        self.assertEqual(report["total_records"], 30_487)
        self.assertEqual(report["flag_counts"]["custom_flag_22"], 4)

    def test_otb_version_and_range(self) -> None:
        report = inspect_otb(ROOT / "assets" / "items" / "items.otb")
        self.assertEqual(report["version"]["csd"], "OTB 3.20.20-8.60")
        self.assertEqual(report["item_nodes"], 25_501)
        self.assertEqual(report["server_ids"]["min"], 100)
        self.assertEqual(report["server_ids"]["max"], 25_600)
        self.assertEqual(report["server_ids"]["gap_count"], 0)

    def test_official_baseline_hashes(self) -> None:
        for relative, expected in BASELINE_SHA256.items():
            with self.subTest(path=relative):
                digest = sha256_file(ROOT / relative)
                self.assertEqual(digest, expected)


if __name__ == "__main__":
    unittest.main()
