from __future__ import annotations

import json
import os
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
            "Tibia.otfi": b"new-otfi",
            "mapanovo.otbm": b"new-map",
            "items.otml": b"new-items-metadata",
            "creatures.otml": b"new-creatures-metadata",
            "effects.otml": b"new-effects-metadata",
            "missiles.otml": b"new-missiles-metadata",
            "things.otml": b"new-things-metadata",
        }
        previous = {
            "items.otb": b"old-otb",
            "items.xml": b"<items>old</items>",
            "Tibia.dat": b"old-dat",
            "Tibia.spr": b"old-spr",
            "Tibia.otfi": b"old-otfi",
            "mapanovo.otbm": b"old-map",
            "items.otml": b"old-items-metadata",
            "creatures.otml": b"old-creatures-metadata",
            "effects.otml": b"old-effects-metadata",
            "missiles.otml": b"old-missiles-metadata",
            "things.otml": b"old-things-metadata",
        }
        for name in ("860", "items", "world"):
            (root / "assets" / name).mkdir(parents=True, exist_ok=True)
        server = workspace / "Server-Data-Nwo" / "data" / "items"
        server_world = workspace / "Server-Data-Nwo" / "data" / "world"
        rme = workspace / "RME 5.0" / "Editor" / "data" / "860"
        client = workspace / "nwo-otclient-mehah-4.0" / "data" / "things" / "860"
        mobile_things = workspace / "nwo-mobile" / "client" / "data" / "things"
        mobile = mobile_things / "860"
        studio_items = workspace / "NWO-STUDIO" / "assets" / "items"
        studio_things_root = workspace / "NWO-STUDIO" / "assets" / "things"
        studio_things = studio_things_root / "1098"
        studio_world = workspace / "NWO-STUDIO" / "assets" / "world"
        server.mkdir(parents=True)
        server_world.mkdir(parents=True)
        rme.mkdir(parents=True)
        client.mkdir(parents=True)
        mobile.mkdir(parents=True)
        studio_items.mkdir(parents=True)
        studio_things.mkdir(parents=True)
        studio_world.mkdir(parents=True)
        for name in ("items.otb", "items.xml"):
            (root / "assets" / "items" / name).write_bytes(canonical[name])
            (server / name).write_bytes(previous[name])
            (rme / name).write_bytes(previous[name])
            (studio_items / name).write_bytes(previous[name])
        for name in ("Tibia.dat", "Tibia.spr"):
            (root / "assets" / "860" / name).write_bytes(canonical[name])
            (client / name).write_bytes(previous[name])
        (client / "Tibia.otfi").write_bytes(b"otfi")
        for name in ("Tibia.dat", "Tibia.spr", "Tibia.otfi"):
            (mobile / name).write_bytes(previous[name])
            (studio_things / name).write_bytes(previous[name])
        (root / "assets" / "860" / "Tibia.otfi").write_bytes(canonical["Tibia.otfi"])
        (root / "assets" / "world" / "mapanovo.otbm").write_bytes(canonical["mapanovo.otbm"])
        (studio_world / "mapanovo.otbm").write_bytes(previous["mapanovo.otbm"])
        (server_world / "mapanovo.otbm").write_bytes(previous["mapanovo.otbm"])
        for name in (
            "items.otml",
            "creatures.otml",
            "effects.otml",
            "missiles.otml",
            "things.otml",
        ):
            (root / name).write_bytes(canonical[name])
            (client.parent / name).write_bytes(previous[name])
            (mobile_things / name).write_bytes(previous[name])
            (studio_things_root / name).write_bytes(previous[name])
        (client.parent / "860.rar").write_bytes(b"old-rar")
        (studio_things_root / "1098.rar").write_bytes(b"old-studio-rar")
        (studio_world / "mapanovo.rar").write_bytes(b"old-map-rar")
        return root, canonical, previous

    @staticmethod
    def fake_rar(
        _rar: Path,
        arguments: list[str],
        cwd: Path | None = None,
    ) -> bytes:
        if arguments[0] == "a":
            payload = b"new-map-rar" if arguments[-1] == "mapanovo.otbm" else b"new-rar"
            Path(arguments[4]).write_bytes(payload)
            return b""
        if arguments[0] == "lb":
            if "mapanovo" in Path(arguments[1]).name:
                return b"mapanovo.otbm\n"
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
                (workspace / "RME 5.0/Editor/data/860/items.otb").read_bytes(),
                canonical["items.otb"],
            )
            self.assertEqual(
                (workspace / "RME 5.0/Editor/data/860/items.xml").read_bytes(),
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
                (workspace / "nwo-mobile/client/data/things/860/Tibia.dat").read_bytes(),
                canonical["Tibia.dat"],
            )
            self.assertEqual(
                (workspace / "nwo-mobile/client/data/things/860/Tibia.spr").read_bytes(),
                canonical["Tibia.spr"],
            )
            self.assertEqual(
                (workspace / "nwo-mobile/client/data/things/860/Tibia.otfi").read_bytes(),
                canonical["Tibia.otfi"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/items/items.otb").read_bytes(),
                canonical["items.otb"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/items/items.xml").read_bytes(),
                canonical["items.xml"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/things/1098/Tibia.dat").read_bytes(),
                canonical["Tibia.dat"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/things/1098/Tibia.spr").read_bytes(),
                canonical["Tibia.spr"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/things/1098/Tibia.otfi").read_bytes(),
                canonical["Tibia.otfi"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/world/mapanovo.otbm").read_bytes(),
                canonical["mapanovo.otbm"],
            )
            self.assertEqual(
                (workspace / "Server-Data-Nwo/data/world/mapanovo.otbm").read_bytes(),
                canonical["mapanovo.otbm"],
            )
            for name in (
                "items.otml",
                "creatures.otml",
                "effects.otml",
                "missiles.otml",
                "things.otml",
            ):
                self.assertEqual(
                    (workspace / "nwo-otclient-mehah-4.0/data/things" / name).read_bytes(),
                    canonical[name],
                )
                self.assertEqual(
                    (workspace / "nwo-mobile/client/data/things" / name).read_bytes(),
                    canonical[name],
                )
                self.assertEqual(
                    (workspace / "NWO-STUDIO/assets/things" / name).read_bytes(),
                    canonical[name],
                )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860.rar").read_bytes(),
                b"new-rar",
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/things/1098.rar").read_bytes(),
                b"new-rar",
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/world/mapanovo.rar").read_bytes(),
                b"new-map-rar",
            )
            self.assertTrue(report["passed"] and report["changed"])
            self.assertFalse(list(workspace.rglob("*.nwoassets.*")))

    @patch("nwoassets.runtime_sync.validate_root", return_value={"passed": True, "errors": [], "warnings": []})
    @patch("nwoassets.runtime_sync.find_rar", return_value=Path("rar.exe"))
    @patch("nwoassets.runtime_sync._run_rar", side_effect=fake_rar.__func__)
    def test_skips_already_equal_spr(self, _rar, _find, _validate) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, canonical, _ = self.make_workspace(directory)
            spr = root.parent / "nwo-otclient-mehah-4.0/data/things/860/Tibia.spr"
            spr.write_bytes(canonical["Tibia.spr"])
            original_replace = os.replace

            def replace_unlocked(source: Path, target: Path) -> None:
                if Path(source) == spr or Path(target) == spr:
                    raise AssertionError("unchanged SPR was replaced")
                original_replace(source, target)

            with patch("nwoassets.runtime_sync.os.replace", side_effect=replace_unlocked):
                report = sync_runtime_assets(root)

            self.assertTrue(report["passed"])
            self.assertEqual(spr.read_bytes(), canonical["Tibia.spr"])
            self.assertTrue(next(entry for entry in report["copies"] if entry["name"] == "Tibia.spr")["already_equal"])

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
                (workspace / "RME 5.0/Editor/data/860/items.xml").read_bytes(),
                previous["items.xml"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860/Tibia.spr").read_bytes(),
                previous["Tibia.spr"],
            )
            self.assertEqual(
                (workspace / "nwo-mobile/client/data/things/860/Tibia.spr").read_bytes(),
                previous["Tibia.spr"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/things/1098/Tibia.spr").read_bytes(),
                previous["Tibia.spr"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/world/mapanovo.otbm").read_bytes(),
                previous["mapanovo.otbm"],
            )
            self.assertEqual(
                (workspace / "Server-Data-Nwo/data/world/mapanovo.otbm").read_bytes(),
                previous["mapanovo.otbm"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/creatures.otml").read_bytes(),
                previous["creatures.otml"],
            )
            self.assertEqual(
                (workspace / "nwo-mobile/client/data/things/effects.otml").read_bytes(),
                previous["effects.otml"],
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/things/things.otml").read_bytes(),
                previous["things.otml"],
            )
            self.assertEqual(
                (workspace / "nwo-otclient-mehah-4.0/data/things/860.rar").read_bytes(),
                b"old-rar",
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/things/1098.rar").read_bytes(),
                b"old-studio-rar",
            )
            self.assertEqual(
                (workspace / "NWO-STUDIO/assets/world/mapanovo.rar").read_bytes(),
                b"old-map-rar",
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
