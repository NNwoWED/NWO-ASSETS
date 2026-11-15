from __future__ import annotations

from pathlib import Path
import unittest

from nwoassets.client import inspect_dat, inspect_spr, read_dat_header
from nwoassets.content import sha256_file
from nwoassets.otb import inspect_otb
from nwoassets.otfi import parse_otfi


ROOT = Path(__file__).resolve().parents[1]

BASELINE_SHA256 = {
    "assets/860/Tibia.dat": "39546B09CE79A0CA5C087300AE1BD4CAA6BA41113DB7E7E47C92302BFAAD302F",
    "assets/860/Tibia.spr": "D36E7546CDB9BCF6618A729F86E07E2E3D3D4BFA17D3F89D37CF5836C5D9BCEB",
    "assets/860/Tibia.otfi": "7743548835944BC799CB871A4E5DEF84F7AF76815031871B9CE74B5EC0E8ADD3",
    "assets/items/items.otb": "88B3C31F90FB131D99C1FB6384B1ADFC08C017C11B1BB8B4FB8D1D573CB2132C",
    "assets/world/mapanovo.otbm": "ABB09C367200FE91408756E2ED7C135382F231F538849BC3B601D10207CE2D8C",
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
        self.assertEqual(dat["max_item_id"], 26617)
        self.assertEqual(spr["signature"], "0x4C220594")
        self.assertEqual(spr["sprite_count"], 313748)
        self.assertEqual(spr["zero_offsets"], 0)

    def test_dat_parses_to_eof(self) -> None:
        report = inspect_dat(
            ROOT / "assets" / "860" / "Tibia.dat",
            self.otfi,
            expected_metadata_reader=5,
            sprite_count=313748,
        )
        self.assertEqual(report["parsed_end_offset"], 4_719_242)
        self.assertEqual(report["total_records"], 32_403)
        self.assertEqual(report["flag_counts"]["custom_flag_22"], 4)

    def test_otb_version_and_range(self) -> None:
        report = inspect_otb(ROOT / "assets" / "items" / "items.otb")
        self.assertEqual(report["version"]["csd"], "OTB 3.20.20-8.60")
        self.assertEqual(report["item_nodes"], 27_403)
        self.assertEqual(report["server_ids"]["min"], 100)
        self.assertEqual(report["server_ids"]["max"], 27_502)
        self.assertEqual(report["server_ids"]["gap_count"], 0)

    def test_official_baseline_hashes(self) -> None:
        for relative, expected in BASELINE_SHA256.items():
            with self.subTest(path=relative):
                digest = sha256_file(ROOT / relative)
                self.assertEqual(digest, expected)


if __name__ == "__main__":
    unittest.main()
