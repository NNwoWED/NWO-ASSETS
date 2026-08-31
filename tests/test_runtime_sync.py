from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nwoassets.errors import FormatError
from nwoassets.cli import main
from nwoassets.runtime_sync import sync_runtime_assets


class RuntimeSyncTests(unittest.TestCase):
    def make_workspace(self, directory: str) -> tuple[Path, dict[str, bytes], dict[str, bytes]]:
        workspace = Path(directory)
        root = workspace / "NWO-ASSETS"
        canonical = {
            "items.otb": b"new-otb",
            "items.xml": b"<items>new</items>",
            "Tibia.dat": b"new-dat",
            "Tibia.spr": b"new-spr",
        }
        previous = {
            "items.otb": b"old-otb",
            "items.xml": b"<items>old</items>",
            "Tibia.dat": b"old-dat",
            "Tibia.spr": b"old-spr",
        }
        for name in ("860", "items", "world"):
            (root / "assets" / name).mkdir(parents=True, exist_ok=True)
        server = workspace / "Server-Data-Nwo" / "data" / "items"
        client = workspace / "nwo-otclient-mehah-4.0" / "data" / "things" / "860"
        server.mkdir(parents=True)
        client.mkdir(parents=True)
        for name in ("items.otb", "items.xml"):
            (root / "assets" / "items" / name).write_bytes(canonical[name])
            (server / name).write_bytes(previous[name])
        for name in ("Tibia.dat", "Tibia.spr"):
            (root / "assets" / "860" / name).write_bytes(canonical[name])
            (client / name).write_bytes(previous[name])
        (client / "Tibia.otfi").write_bytes(b"otfi")
        (client.parent / "860.rar").write_bytes(b"old-rar")
        return root, canonical, previous

    @staticmethod
    def fake_rar(
        _rar: Path,
        arguments: list[str],
        cwd: Path | None = None,
    ) -> bytes:
        if arguments[0] == "a":
            Path(arguments[4]).write_bytes(b"new-rar")
            return b""
        if arguments[0] == "lb":
            return b"860\\Tibia.dat\n860\\Tibia.otfi\n860\\Tibia.spr\n860\n"
        return b""

    @patch("nwoassets.runtime_sync.validate_root", return_value={"passed": True, "errors": [], "warnings": []})
    @patch("nwoassets.runtime_sync.find_rar", return_value=Path("rar.exe"))
    @patch("nwoassets.runtime_sync._run_rar", side_effect=fake_rar.__func__)
    def test_publishes_all_runtime_files_and_archive(self, _rar, _find, _validate) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, canonical, _ = self.make_workspace(directory)
            report = sync_runtime_assets(root)
            workspace = root.parent
            self.assertEqual(
                (workspace / "Server-Data-Nwo/data/items/items.otb").read_bytes(),
                canonical["items.otb"],
            )
            self.assertEqual(
                (workspace / "Server-Data-Nwo/data/items/items.xml").read_bytes(),
                canonical["items.xml"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860/Tibia.dat").read_bytes(),
                canonical["Tibia.dat"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860/Tibia.spr").read_bytes(),
                canonical["Tibia.spr"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860.rar").read_bytes(),
                b"new-rar",
            )
            self.assertTrue(report["passed"] and report["changed"])
            self.assertFalse(list(workspace.rglob("*.nwoassets.*")))

    @patch("nwoassets.runtime_sync.validate_root", return_value={"passed": True, "errors": [], "warnings": []})
    @patch("nwoassets.runtime_sync.find_rar", return_value=Path("rar.exe"))
    @patch("nwoassets.runtime_sync._run_rar", side_effect=FormatError("rar falhou"))
    def test_rolls_back_when_archive_fails(self, _rar, _find, _validate) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _, previous = self.make_workspace(directory)
            with self.assertRaises(FormatError):
                sync_runtime_assets(root)
            workspace = root.parent
            self.assertEqual(
                (workspace / "Server-Data-Nwo/data/items/items.otb").read_bytes(),
                previous["items.otb"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860/Tibia.spr").read_bytes(),
                previous["Tibia.spr"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860.rar").read_bytes(),
                b"old-rar",
            )
            self.assertFalse(list(workspace.rglob("*.nwoassets.*")))

    @patch("nwoassets.cli.sync_runtime_assets", side_effect=FormatError("falha simulada"))
    def test_cli_writes_failure_report(self, _sync) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failure.json"
            exit_code = main(["sync-runtime", directory, "-o", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 2)
            self.assertFalse(report["passed"])
            self.assertEqual(report["error"], "falha simulada")


if __name__ == "__main__":
    unittest.main()
