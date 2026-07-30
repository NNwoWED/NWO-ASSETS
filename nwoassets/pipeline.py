from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import struct

from . import __version__
from .client import inspect_dat, inspect_spr, read_dat_header
from .content import inspect_otml, inspect_world, inspect_xml, scan_directory
from .errors import FormatError
from .otb import inspect_otb
from .otfi import parse_otfi
from .profiles import detect_profile


def _single(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob("*") if path.is_file() and path.name.casefold() == name.casefold()]
    if len(matches) != 1:
        raise FormatError(
            f"esperado exatamente um {name} em {root}; encontrados {len(matches)}"
        )
    return matches[0]


def inspect_client(root: Path, *, deep_spr: bool = False) -> dict[str, object]:
    root = root.resolve()
    otfi_path = _single(root, "Tibia.otfi")
    otfi = parse_otfi(otfi_path)
    dat_path = (otfi_path.parent / otfi.metadata_file).resolve()
    spr_path = (otfi_path.parent / otfi.sprites_file).resolve()
    otb_path = _single(root, "items.otb")
    for path in (dat_path, spr_path, otb_path):
        if not path.is_file():
            raise FormatError(f"arquivo obrigatório ausente: {path}")

    dat_header = read_dat_header(dat_path)
    with spr_path.open("rb") as stream:
        spr_signature_raw = stream.read(4)
    if len(spr_signature_raw) != 4:
        raise FormatError(f"{spr_path}: assinatura truncada")
    spr_signature = struct.unpack("<I", spr_signature_raw)[0]
    profile = detect_profile(int(dat_header["signature_value"]), spr_signature)

    spr = inspect_spr(spr_path, otfi, deep=deep_spr)
    dat = inspect_dat(
        dat_path,
        otfi,
        expected_metadata_reader=profile.metadata_reader,
        sprite_count=int(spr["sprite_count"]),
    )
    otb = inspect_otb(otb_path)

    errors: list[str] = []
    warnings: list[str] = []
    checks = {
        "profile_detected": True,
        "otfi_sprite_size_32": otfi.sprite_size == 32,
        "otfi_sprite_data_size_4096": otfi.sprite_data_size == 4096,
        "dat_signature_matches_profile": dat["signature"]
        == f"0x{profile.dat_signature:08X}",
        "spr_signature_matches_profile": spr["signature"]
        == f"0x{profile.spr_signature:08X}",
        "otb_mentions_client_version": profile.otb_version_hint
        in str(otb["version"]["csd"]),
        "otb_client_ids_fit_dat": (
            otb["client_ids"]["max"] is None
            or int(otb["client_ids"]["max"]) <= int(dat["max_ids"]["items"])
        ),
        "spr_deep_validation": (
            not deep_spr or bool(spr["deep_validation"].get("passed"))
        ),
    }
    for name, passed in checks.items():
        if not passed:
            errors.append(f"check falhou: {name}")
    if otb["server_ids"]["gap_count"]:
        warnings.append(
            f"OTB possui {otb['server_ids']['gap_count']} lacunas entre Server IDs"
        )
    if otb["unknown_attributes"]:
        warnings.append("OTB contém atributos ainda não nomeados pela CLI")

    return {
        "profile": profile.to_dict(),
        "paths": {
            "otfi": str(otfi_path),
            "dat": str(dat_path),
            "spr": str(spr_path),
            "otb": str(otb_path),
        },
        "otfi": otfi.to_dict(),
        "dat": dat,
        "spr": spr,
        "otb": otb,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "passed": not errors,
    }


def inspect_text_configs(root: Path) -> dict[str, object]:
    return {
        "xml": [
            inspect_xml(path)
            for path in sorted(root.rglob("*.xml"))
        ],
        "otml": [
            inspect_otml(path)
            for path in sorted(root.rglob("*.otml"))
        ],
    }


def validate_root(root: Path, *, deep_spr: bool = False) -> dict[str, object]:
    root = root.resolve()
    inventory = scan_directory(root)
    client = inspect_client(root, deep_spr=deep_spr)
    world = inspect_world(root)
    configs = inspect_text_configs(root)
    errors = list(client["errors"])
    warnings = list(client["warnings"])
    fragment_paths = [
        entry["path"] for entry in configs["xml"] if entry["fragment"]
    ]
    if fragment_paths:
        warnings.append(
            "XMLs tratados como fragmento: " + ", ".join(fragment_paths)
        )
    if world["map_variants"] > 1 and not world["identical_map_groups"]:
        warnings.append(
            f"foram encontradas {world['map_variants']} variantes distintas de mapa"
        )
    otb_major = client["otb"]["version"]["major"]
    otb_minor = client["otb"]["version"]["minor"]
    for map_report in world["maps"]:
        if (
            map_report["items_major_version"] != otb_major
            or map_report["items_minor_version"] != otb_minor
        ):
            errors.append(
                f"{map_report['source']}: versão de items "
                f"{map_report['items_major_version']}.{map_report['items_minor_version']} "
                f"difere do OTB {otb_major}.{otb_minor}"
            )
    for archive in world["archives"]:
        for entry in archive["entries"]:
            map_report = entry.get("otbm")
            if map_report and (
                map_report["items_major_version"] != otb_major
                or map_report["items_minor_version"] != otb_minor
            ):
                errors.append(
                    f"{map_report['source']}: versão de items "
                    f"{map_report['items_major_version']}.{map_report['items_minor_version']} "
                    f"difere do OTB {otb_major}.{otb_minor}"
                )
    return {
        "tool_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "inventory": inventory,
        "client": client,
        "world": world,
        "configs": configs,
        "warnings": warnings,
        "errors": errors,
        "passed": not errors,
    }
