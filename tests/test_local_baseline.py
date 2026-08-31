from __future__ import annotations

from pathlib import Path
import unittest

from nwoassets.client import inspect_dat, inspect_spr, read_dat_header
from nwoassets.content import sha256_file
from nwoassets.otb import inspect_otb
from nwoassets.otfi import parse_otfi


ROOT = Path(__file__).resolve().parents[1]

BASELINE_SHA256 = {
    "assets/860/Tibia.dat": "E68A65CA9ABAC59CB24F456D418E964C70F7061E016C7CCD4004C0C9F137D125",
    "assets/860/Tibia.spr": "F9BF2383ADF5601BD90FC18E4C0C1A4880CB473D72B18F87A3D2BA83E1953CA0",
    "assets/860/Tibia.otfi": "7743548835944BC799CB871A4E5DEF84F7AF76815031871B9CE74B5EC0E8ADD3",
    "assets/items/items.otb": "013E2829400C4BCAC9AC536B69EC5DDA636E9BCC94E9344248E1D13913087153",
    "assets/world/mapanovo.otbm": "3F1396A9C7F1817A406897B42D163C25A73CE55E86B072E92416356C96FD3650",
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
        self.assertEqual(dat["max_item_id"], 24522)
        self.assertEqual(spr["signature"], "0x4C220594")
        self.assertEqual(spr["sprite_count"], 252158)
        self.assertEqual(spr["zero_offsets"], 0)

    def test_dat_parses_to_eof(self) -> None:
        report = inspect_dat(
            ROOT / "assets" / "860" / "Tibia.dat",
            self.otfi,
            expected_metadata_reader=5,
            sprite_count=252158,
        )
        self.assertEqual(report["parsed_end_offset"], 4_369_272)
        self.assertEqual(report["total_records"], 30_294)
        self.assertEqual(report["flag_counts"]["custom_flag_22"], 4)

    def test_otb_version_and_range(self) -> None:
        report = inspect_otb(ROOT / "assets" / "items" / "items.otb")
        self.assertEqual(report["version"]["csd"], "OTB 3.20.20-8.60")
        self.assertEqual(report["item_nodes"], 25_308)
        self.assertEqual(report["server_ids"]["min"], 100)
        self.assertEqual(report["server_ids"]["max"], 25_407)
        self.assertEqual(report["server_ids"]["gap_count"], 0)

    def test_official_baseline_hashes(self) -> None:
        for relative, expected in BASELINE_SHA256.items():
            with self.subTest(path=relative):
                digest = sha256_file(ROOT / relative)
                self.assertEqual(digest, expected)


if __name__ == "__main__":
    unittest.main()
