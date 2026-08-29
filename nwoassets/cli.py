from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Callable

from . import __version__
from .content import inspect_world, scan_directory
from .errors import NwoAssetsError
from .importer import import_items
from .otbm import inspect_map_position
from .pipeline import inspect_client, inspect_text_configs, validate_root
from .properties import edit_item_properties
from .versioning import create_version


def _write_report(report: dict[str, object], output: str | None) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        print(f"Relatorio gravado em {path.resolve()}")
    else:
        sys.stdout.write(payload)


def _root(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"diretório não encontrado: {path}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nwoassets",
        description="Inspeção, versionamento e importação segura dos assets Tibia/NWO MAPS.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(name: str, help_text: str) -> argparse.ArgumentParser:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("root", nargs="?", default=".", type=_root)
        command.add_argument("-o", "--output", help="grava o relatório JSON neste caminho")
        return command

    common("scan", "inventaria e calcula SHA-256 de todos os arquivos")
    client = common("inspect-client", "inspeciona OTFI, DAT, SPR e OTB")
    client.add_argument(
        "--deep-spr",
        action="store_true",
        help="valida cabeçalho e RLE de todos os blocos SPR (mais demorado)",
    )
    common("inspect-world", "inspeciona OTBM, ZIP e XMLs do diretório world")
    common("inspect-configs", "inspeciona XML e OTML")
    validate = common("validate", "executa a inspeção integrada da pasta")
    validate.add_argument(
        "--deep-spr",
        action="store_true",
        help="valida cabeçalho e RLE de todos os blocos SPR",
    )
    importer = subparsers.add_parser(
        "import-items",
        help="versiona e importa PNGs em Client IDs existentes na pasta assets",
    )
    importer.add_argument("root", nargs="?", default=".", type=_root)
    importer.add_argument("manifest", type=Path)
    importer.add_argument("-o", "--output", help="grava o relatório JSON neste caminho")
    importer.add_argument(
        "--deep-spr",
        action="store_true",
        help="valida todos os blocos RLE antes e depois da importação",
    )
    common("create-version", "cria 860.rar, items.rar e world.zip antes de alterações")
    properties = subparsers.add_parser(
        "edit-item-properties",
        help="versiona e edita flags DAT/OTB de itens existentes",
    )
    properties.add_argument("root", nargs="?", default=".", type=_root)
    properties.add_argument("manifest", type=Path)
    properties.add_argument("-o", "--output", help="grava o relatório JSON neste caminho")
    properties.add_argument("--deep-spr", action="store_true", help="valida todos os blocos RLE")
    position = subparsers.add_parser(
        "inspect-map-position",
        help="inspeciona a pilha de itens em uma coordenada OTBM",
    )
    position.add_argument("root", nargs="?", default=".", type=_root)
    position.add_argument("x", type=int)
    position.add_argument("y", type=int)
    position.add_argument("z", type=int)
    position.add_argument("-o", "--output", help="grava o relatório JSON neste caminho")
    return parser


def main(argv: list[str] | None = None) -> int:
    if os.name == "nt":
        # Evita mojibake em terminais Windows cuja codificação herdada não é UTF-8.
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    actions: dict[str, Callable[[], dict[str, object]]] = {
        "scan": lambda: scan_directory(args.root),
        "inspect-client": lambda: inspect_client(
            args.root, deep_spr=args.deep_spr
        ),
        "inspect-world": lambda: inspect_world(args.root),
        "inspect-configs": lambda: inspect_text_configs(args.root),
        "validate": lambda: validate_root(args.root, deep_spr=args.deep_spr),
        "import-items": lambda: import_items(
            args.root,
            args.manifest,
            deep_spr=args.deep_spr,
        ),
        "create-version": lambda: create_version(args.root),
        "edit-item-properties": lambda: edit_item_properties(
            args.root, args.manifest, deep_spr=args.deep_spr
        ),
        "inspect-map-position": lambda: inspect_map_position(
            args.root, args.x, args.y, args.z
        ),
    }
    try:
        report = actions[args.command]()
        _write_report(report, args.output)
        if args.command in {
            "validate", "import-items", "create-version", "edit-item-properties",
            "inspect-map-position",
        } and not report.get("passed", False):
            return 1
        return 0
    except NwoAssetsError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"erro de I/O: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
