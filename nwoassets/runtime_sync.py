from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil

from . import __version__
from .content import sha256_file
from .errors import FormatError
from .pipeline import validate_root
from .versioning import _run_rar, find_rar, require_asset_layout


def _transaction_path(target: Path, state: str) -> Path:
    suffix = target.suffix
    stem = target.name[: -len(suffix)] if suffix else target.name
    return target.with_name(f".{stem}.nwoassets.{state}{suffix}")


def _runtime_transaction_path(target: Path, state: str, client_860: Path) -> Path:
    path = _transaction_path(target, state)
    if target.parent == client_860:
        # Os temporários de DAT/SPR não podem entrar no conteúdo compactado.
        return client_860.parent / path.name
    return path


def _require_directory(path: Path, description: str) -> Path:
    path = path.resolve()
    if not path.is_dir():
        raise FormatError(f"{description} não encontrado: {path}")
    return path


def _runtime_paths(
    root: Path,
    client_root: Path | None = None,
) -> tuple[
    dict[str, Path],
    dict[str, Path],
    Path,
    Path,
    Path,
    Path,
    Path,
]:
    root = root.resolve()
    layout = require_asset_layout(root)
    workspace = root.parent.resolve()
    server_items = _require_directory(
        workspace / "Server-Data-Nwo" / "data" / "items",
        "diretório de items do servidor",
    )
    server_world = _require_directory(
        workspace / "Server-Data-Nwo" / "data" / "world",
        "diretorio world do servidor",
    )
    rme_items = _require_directory(
        workspace / "RME 5.0" / "Editor" / "data" / "860",
        "diretório de items do RME",
    )
    client_things = _require_directory(
        (client_root or workspace / "nwo-otclient-mehah-4.0") / "data" / "things",
        "diretório things do client",
    )
    client_860 = _require_directory(client_things / "860", "diretório 860 do client")
    mobile_things = _require_directory(
        workspace / "nwo-mobile" / "client" / "data" / "things",
        "diretorio things do client mobile",
    )
    mobile_860 = (mobile_things / "860").resolve()
    if mobile_860.exists() and not mobile_860.is_dir():
        raise FormatError(f"destino 860 do client mobile nao e diretorio: {mobile_860}")
    studio_assets = _require_directory(
        workspace / "NWO-STUDIO" / "assets",
        "diretorio de assets do NWO-STUDIO",
    )
    studio_items = _require_directory(
        studio_assets / "items",
        "diretorio de items do NWO-STUDIO",
    )
    studio_things = _require_directory(
        studio_assets / "things" / "1098",
        "diretorio things/1098 do NWO-STUDIO",
    )
    studio_world = _require_directory(
        studio_assets / "world",
        "diretorio world do NWO-STUDIO",
    )
    metadata_names = (
        "items.otml",
        "creatures.otml",
        "effects.otml",
        "missiles.otml",
        "things.otml",
    )
    sources = {
        "items.otb": layout["items"] / "items.otb",
        "items.xml": layout["items"] / "items.xml",
        "server/mapanovo.otbm": layout["world"] / "mapanovo.otbm",
        "rme/items.otb": layout["items"] / "items.otb",
        "rme/items.xml": layout["items"] / "items.xml",
        "Tibia.dat": layout["860"] / "Tibia.dat",
        "Tibia.spr": layout["860"] / "Tibia.spr",
        "mobile/Tibia.dat": layout["860"] / "Tibia.dat",
        "mobile/Tibia.spr": layout["860"] / "Tibia.spr",
        "mobile/Tibia.otfi": layout["860"] / "Tibia.otfi",
        "studio/items.otb": layout["items"] / "items.otb",
        "studio/items.xml": layout["items"] / "items.xml",
        "studio/Tibia.dat": layout["860"] / "Tibia.dat",
        "studio/Tibia.spr": layout["860"] / "Tibia.spr",
        "studio/Tibia.otfi": layout["860"] / "Tibia.otfi",
        "studio/mapanovo.otbm": layout["world"] / "mapanovo.otbm",
    }
    for name in metadata_names:
        sources[f"metadata/{name}"] = root / name
        sources[f"mobile/metadata/{name}"] = root / name
        sources[f"studio/metadata/{name}"] = root / name
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FormatError("arquivos canônicos ausentes: " + ", ".join(missing))
    targets = {
        "items.otb": server_items / "items.otb",
        "items.xml": server_items / "items.xml",
        "server/mapanovo.otbm": server_world / "mapanovo.otbm",
        "rme/items.otb": rme_items / "items.otb",
        "rme/items.xml": rme_items / "items.xml",
        "Tibia.dat": client_860 / "Tibia.dat",
        "Tibia.spr": client_860 / "Tibia.spr",
        "mobile/Tibia.dat": mobile_860 / "Tibia.dat",
        "mobile/Tibia.spr": mobile_860 / "Tibia.spr",
        "mobile/Tibia.otfi": mobile_860 / "Tibia.otfi",
        "studio/items.otb": studio_items / "items.otb",
        "studio/items.xml": studio_items / "items.xml",
        "studio/Tibia.dat": studio_things / "Tibia.dat",
        "studio/Tibia.spr": studio_things / "Tibia.spr",
        "studio/Tibia.otfi": studio_things / "Tibia.otfi",
        "studio/mapanovo.otbm": studio_world / "mapanovo.otbm",
    }
    for name in metadata_names:
        targets[f"metadata/{name}"] = client_things / name
        targets[f"mobile/metadata/{name}"] = mobile_things / name
        targets[f"studio/metadata/{name}"] = studio_assets / "things" / name
    return (
        sources,
        targets,
        client_860,
        client_things / "860.rar",
        mobile_860,
        studio_assets / "things" / "1098.rar",
        studio_world / "mapanovo.rar",
    )


def _expected_rar_entries(client_860: Path) -> set[str]:
    entries = {"860"}
    for path in client_860.rglob("*"):
        relative = Path("860") / path.relative_to(client_860)
        entries.add(str(relative).replace("/", "\\").casefold())
    return entries


def _inspect_rar(rar: Path, archive: Path, client_860: Path) -> list[str]:
    _run_rar(rar, ["t", "-idq", str(archive)])
    listed = _run_rar(rar, ["lb", str(archive)]).decode("utf-8", errors="replace")
    actual = {
        line.strip().replace("/", "\\").casefold()
        for line in listed.splitlines()
        if line.strip()
    }
    expected = _expected_rar_entries(client_860)
    if actual != expected:
        raise FormatError(
            f"conteúdo inesperado em {archive.name}: "
            f"esperado={sorted(expected)}, encontrado={sorted(actual)}"
        )
    return sorted(actual)


def _inspect_single_file_rar(rar: Path, archive: Path, filename: str) -> list[str]:
    _run_rar(rar, ["t", "-idq", str(archive)])
    listed = _run_rar(rar, ["lb", str(archive)]).decode("utf-8", errors="replace")
    actual = [
        line.strip().replace("/", "\\")
        for line in listed.splitlines()
        if line.strip()
    ]
    if [entry.casefold() for entry in actual] != [filename.casefold()]:
        raise FormatError(
            f"conteudo inesperado em {archive.name}: "
            f"esperado={[filename]}, encontrado={actual}"
        )
    return actual


def _prepare_copy(source: Path, target: Path, client_860: Path) -> Path:
    pending = _runtime_transaction_path(target, "pending", client_860)
    if pending.exists():
        raise FormatError(f"arquivo temporário pendente: {pending}")
    shutil.copy2(source, pending)
    if sha256_file(pending) != sha256_file(source):
        pending.unlink(missing_ok=True)
        raise FormatError(f"hash da cópia temporária diverge: {target}")
    return pending


def _rollback(published: list[Path], backups: dict[Path, Path]) -> None:
    for target in reversed(published):
        target.unlink(missing_ok=True)
    for target, backup in reversed(list(backups.items())):
        if backup.exists():
            os.replace(backup, target)


def sync_runtime_assets(root: Path, *, dry_run: bool = False, client_root: Path | None = None) -> dict[str, object]:
    root = root.resolve()
    (
        sources,
        targets,
        client_860,
        archive,
        mobile_860,
        studio_things_archive,
        studio_map_archive,
    ) = _runtime_paths(root, client_root)
    validation = validate_root(root, deep_spr=True)
    if not validation.get("passed", False):
        raise FormatError(f"baseline canônica reprovou: {validation.get('errors', [])}")

    copies = []
    for name, source in sources.items():
        target = targets[name]
        source_hash = sha256_file(source)
        target_hash = sha256_file(target) if target.is_file() else None
        copies.append({
            "name": name,
            "source": str(source),
            "target": str(target),
            "size": source.stat().st_size,
            "sha256": source_hash,
            "already_equal": target_hash == source_hash,
        })

    report: dict[str, object] = {
        "tool_version": __version__,
        "generated_at": datetime.now().astimezone().isoformat(),
        "root": str(root),
        "dry_run": dry_run,
        "validation": {
            "passed": True,
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
        },
        "copies": copies,
        "archive": {"path": str(archive)},
        "studio_archives": {
            "things": {"path": str(studio_things_archive)},
            "world": {"path": str(studio_map_archive)},
        },
        "passed": True,
    }
    if dry_run:
        report["changed"] = False
        return report

    changed_names = {entry["name"] for entry in copies if not entry["already_equal"]}
    pending: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    mobile_directory_created = False
    rar = find_rar()
    archive_pending = _transaction_path(archive, "pending")
    studio_things_archive_pending = _transaction_path(studio_things_archive, "pending")
    studio_map_archive_pending = _transaction_path(studio_map_archive, "pending")
    all_targets = [
        *targets.values(),
        archive,
        studio_things_archive,
        studio_map_archive,
    ]
    reserved = [
        path
        for target in all_targets
        for path in (
            _runtime_transaction_path(target, "pending", client_860),
            _runtime_transaction_path(target, "backup", client_860),
        )
        if path.exists()
    ]
    if reserved:
        raise FormatError(
            "sincronização bloqueada por temporários pendentes: "
            + ", ".join(str(path) for path in reserved)
        )

    try:
        if not mobile_860.exists():
            mobile_860.mkdir()
            mobile_directory_created = True
        for name, target in targets.items():
            if name in changed_names:
                pending[target] = _prepare_copy(sources[name], target, client_860)
        for name, target in targets.items():
            if name not in changed_names:
                continue
            backup = _runtime_transaction_path(target, "backup", client_860)
            if target.exists():
                os.replace(target, backup)
                backups[target] = backup
            os.replace(pending[target], target)
            published.append(target)

        _run_rar(
            rar,
            ["a", "-ma5", "-m3", "-idq", str(archive_pending), "860"],
            cwd=client_860.parent,
        )
        _inspect_rar(rar, archive_pending, client_860)
        shutil.copy2(archive_pending, studio_things_archive_pending)
        if sha256_file(studio_things_archive_pending) != sha256_file(archive_pending):
            raise FormatError("hash do 1098.rar preparado para o NWO-STUDIO diverge")
        _inspect_rar(rar, studio_things_archive_pending, client_860)

        studio_map_source = sources["studio/mapanovo.otbm"]
        _run_rar(
            rar,
            ["a", "-ma5", "-m3", "-idq", str(studio_map_archive_pending), studio_map_source.name],
            cwd=studio_map_source.parent,
        )
        _inspect_single_file_rar(rar, studio_map_archive_pending, studio_map_source.name)

        for final_archive, pending_archive in (
            (archive, archive_pending),
            (studio_things_archive, studio_things_archive_pending),
            (studio_map_archive, studio_map_archive_pending),
        ):
            archive_backup = _runtime_transaction_path(final_archive, "backup", client_860)
            if final_archive.exists():
                os.replace(final_archive, archive_backup)
                backups[final_archive] = archive_backup
            os.replace(pending_archive, final_archive)
            published.append(final_archive)

        for name, target in targets.items():
            if sha256_file(target) != sha256_file(sources[name]):
                raise FormatError(f"hash publicado diverge da baseline: {target}")
        entries = _inspect_rar(rar, archive, client_860)
        studio_things_entries = _inspect_rar(rar, studio_things_archive, client_860)
        studio_map_entries = _inspect_single_file_rar(
            rar,
            studio_map_archive,
            sources["studio/mapanovo.otbm"].name,
        )
        report["archive"] = {
            "path": str(archive),
            "size": archive.stat().st_size,
            "sha256": sha256_file(archive),
            "entries": entries,
            "rar_executable": str(rar),
        }
        report["studio_archives"] = {
            "things": {
                "path": str(studio_things_archive),
                "size": studio_things_archive.stat().st_size,
                "sha256": sha256_file(studio_things_archive),
                "entries": studio_things_entries,
                "rar_executable": str(rar),
            },
            "world": {
                "path": str(studio_map_archive),
                "size": studio_map_archive.stat().st_size,
                "sha256": sha256_file(studio_map_archive),
                "entries": studio_map_entries,
                "rar_executable": str(rar),
            },
        }
        report["changed"] = True
        for backup in backups.values():
            backup.unlink(missing_ok=True)
        return report
    except BaseException:
        _rollback(published, backups)
        raise
    finally:
        for path in pending.values():
            path.unlink(missing_ok=True)
        archive_pending.unlink(missing_ok=True)
        studio_things_archive_pending.unlink(missing_ok=True)
        studio_map_archive_pending.unlink(missing_ok=True)
        if mobile_directory_created and mobile_860.exists() and not any(mobile_860.iterdir()):
            mobile_860.rmdir()
