from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from nwoassets.errors import FormatError
from nwoassets.versioning import create_version, find_rar, require_asset_layout


class AssetLayoutTests(unittest.TestCase):
    def test_requires_three_asset_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FormatError):
                require_asset_layout(root)
            for name in ("860", "items", "world"):
                (root / "assets" / name).mkdir(parents=True, exist_ok=True)
            layout = require_asset_layout(root)
        self.assertEqual(layout["root"].name, "assets")


@unittest.skipUnless(
    any(
        candidate.is_file()
        for candidate in (
            Path(r"C:\Program Files\WinRAR\rar.exe"),
            Path(r"C:\Program Files (x86)\WinRAR\rar.exe"),
        )
    ),
    "rar.exe ausente",
)
class VersionArchiveTests(unittest.TestCase):
    def test_creates_required_archives_and_excludes_xml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("860", "items", "world"):
                (root / "assets" / name).mkdir(parents=True, exist_ok=True)
            (root / "assets" / "860" / "Tibia.dat").write_bytes(b"dat")
            (root / "assets" / "860" / "Tibia.spr").write_bytes(b"spr")
            (root / "assets" / "items" / "items.otb").write_bytes(b"otb")
            (root / "assets" / "items" / "items.xml").write_text(
                "<items />", encoding="utf-8"
            )
            (root / "assets" / "world" / "map.otbm").write_bytes(b"otbm")
            (root / "assets" / "world" / "spawn.xml").write_text(
                "<spawns />", encoding="utf-8"
            )

            report = create_version(root)
            version_root = Path(report["root"])
            manifest = json.loads((version_root / "version.json").read_text("utf-8"))
            with zipfile.ZipFile(version_root / "world.zip") as archive:
                world_entries = archive.namelist()

            self.assertTrue((version_root / "860.rar").is_file())
            self.assertTrue((version_root / "items.rar").is_file())
            self.assertEqual(world_entries, ["map.otbm"])
            self.assertTrue(manifest["items_xml_excluded"])
            self.assertFalse(
                any(source["path"].endswith(".xml") for source in manifest["sources"])
            )
            self.assertEqual(find_rar().name.casefold(), "rar.exe")

    def test_rejects_reserved_transaction_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("860", "items", "world"):
                (root / "assets" / name).mkdir(parents=True, exist_ok=True)
            (root / "assets" / "860" / "Tibia.dat").write_bytes(b"dat")
            (root / "assets" / "860" / ".Tibia.dat.nwoassets.pending").write_bytes(
                b"pending"
            )
            (root / "assets" / "items" / "items.otb").write_bytes(b"otb")
            (root / "assets" / "world" / "map.otbm").write_bytes(b"otbm")
            with self.assertRaises(FormatError):
                create_version(root)


if __name__ == "__main__":
    unittest.main()
