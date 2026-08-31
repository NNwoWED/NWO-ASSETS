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


def _runtime_paths(root: Path) -> tuple[dict[str, Path], dict[str, Path], Path, Path]:
    root = root.resolve()
    layout = require_asset_layout(root)
    workspace = root.parent.resolve()
    server_items = _require_directory(
        workspace / "Server-Data-Nwo" / "data" / "items",
        "diretório de items do servidor",
    )
    client_things = _require_directory(
        workspace / "nwo-otclient-mehah-4.0" / "data" / "things",
        "diretório things do client",
    )
    client_860 = _require_directory(client_things / "860", "diretório 860 do client")
    sources = {
        "items.otb": layout["items"] / "items.otb",
        "items.xml": layout["items"] / "items.xml",
        "Tibia.dat": layout["860"] / "Tibia.dat",
        "Tibia.spr": layout["860"] / "Tibia.spr",
    }
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FormatError("arquivos canônicos ausentes: " + ", ".join(missing))
    targets = {
        "items.otb": server_items / "items.otb",
        "items.xml": server_items / "items.xml",
        "Tibia.dat": client_860 / "Tibia.dat",
        "Tibia.spr": client_860 / "Tibia.spr",
    }
    return sources, targets, client_860, client_things / "860.rar"


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


def sync_runtime_assets(root: Path, *, dry_run: bool = False) -> dict[str, object]:
    root = root.resolve()
    sources, targets, client_860, archive = _runtime_paths(root)
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
        "passed": True,
    }
    if dry_run:
        report["changed"] = False
        return report

    pending: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    published: list[Path] = []
    rar = find_rar()
    archive_pending = _transaction_path(archive, "pending")
    all_targets = [*targets.values(), archive]
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
        for name, target in targets.items():
            pending[target] = _prepare_copy(sources[name], target, client_860)
        for target in targets.values():
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
        archive_backup = _runtime_transaction_path(archive, "backup", client_860)
        if archive.exists():
            os.replace(archive, archive_backup)
            backups[archive] = archive_backup
        os.replace(archive_pending, archive)
        published.append(archive)

        for name, target in targets.items():
            if sha256_file(target) != sha256_file(sources[name]):
                raise FormatError(f"hash publicado diverge da baseline: {target}")
        entries = _inspect_rar(rar, archive, client_860)
        report["archive"] = {
            "path": str(archive),
            "size": archive.stat().st_size,
            "sha256": sha256_file(archive),
            "entries": entries,
            "rar_executable": str(rar),
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
