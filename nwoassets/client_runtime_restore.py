"""Restore an isolated client checkout from its own verified, versioned archive.

This never changes the canonical baseline or copies assets to another runtime.
Expected DAT/SPR hashes must be provided from a previously validated version.
"""
from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
import os
from pathlib import Path, PureWindowsPath
import shutil
import tempfile

from . import __version__
from .content import sha256_file
from .errors import FormatError
from .pipeline import validate_root
from .versioning import find_rar, _run_rar


@contextmanager
def _recovery_directory(root: Path):
    staging = Path(tempfile.mkdtemp(prefix=".client-runtime-restore-", dir=root / "reports"))
    try:
        yield staging
    except BaseException:
        # Keep the extraction/backups on any failure, including rollback failure.
        raise
    else:
        shutil.rmtree(staging)


def restore_client_runtime(root: Path, *, client_root: Path, archive: Path,
                           dat_sha256: str, spr_sha256: str) -> dict[str, object]:
    root, client_root, archive = root.resolve(), client_root.resolve(), archive.resolve()
    target = (client_root / "data/things/860").resolve()
    if not target.is_dir() or target == (root / "assets/860").resolve() or root in target.parents:
        raise FormatError("destino deve ser o runtime isolado de um client, fora da baseline")
    expected = {"Tibia.dat": dat_sha256.upper(), "Tibia.spr": spr_sha256.upper()}
    if any(len(value) != 64 or any(c not in '0123456789ABCDEF' for c in value) for value in expected.values()):
        raise FormatError("informe hashes SHA-256 DAT/SPR da versao anterior validada")
    validation = validate_root(root, deep_spr=True)
    if not validation.get("passed", False):
        raise FormatError("baseline canonica reprovou; restauracao do runtime cancelada")
    rar = find_rar()
    _run_rar(rar, ["t", "-idq", str(archive)])
    listed = _run_rar(rar, ["lb", str(archive)]).decode("utf8", errors="replace")
    allowed = {"860", "860/tibia.dat", "860/tibia.spr", "860/tibia.otfi", "860/.gitattributes"}
    entries = set()
    for line in listed.splitlines():
        name = line.strip().replace("\\", "/")
        if not name:
            continue
        path = PureWindowsPath(name)
        if path.is_absolute() or path.drive or ".." in path.parts or name.casefold() not in allowed:
            raise FormatError(f"entrada inesperada no pacote do client: {name}")
        entries.add(name.casefold())
    if not {"860/tibia.dat", "860/tibia.spr", "860/tibia.otfi"}.issubset(entries):
        raise FormatError("pacote do client nao contem o conjunto DAT/SPR/OTFI completo")
    (root / "reports").mkdir(exist_ok=True)
    with _recovery_directory(root) as staging:
        extracted, backup = staging / "extracted", staging / "backup"
        extracted.mkdir()
        backup.mkdir()
        _run_rar(rar, ["x", "-idq", "-o+", "-y", str(archive), str(extracted) + os.sep])
        source = extracted / "860"
        files = list(source.iterdir())
        if any(p.is_symlink() or not p.is_file() or p.resolve().parent != source.resolve() for p in files):
            raise FormatError("extracao do client contem arquivo especial ou diretorio inesperado")
        actual_entries = {"860/" + p.name.casefold() for p in files}
        if actual_entries != entries - {"860"}:
            raise FormatError("conteudo extraido diverge do inventario do arquivo")
        for name, digest in expected.items():
            if sha256_file(source / name).upper() != digest:
                raise FormatError(f"hash anterior validado diverge: {name}")
        records = [{"name": p.name, "sha256": sha256_file(p),
                    "previous_sha256": sha256_file(target / p.name) if (target / p.name).is_file() else None}
                   for p in files]
        attempted = []
        try:
            for p in files:
                final = target / p.name
                if final.exists():
                    if not final.is_file() or final.is_symlink():
                        raise FormatError(f"destino nao e arquivo regular: {final}")
                    os.replace(final, backup / p.name)
                attempted.append((final, backup / p.name))
                os.replace(p, final)
            for record in records:
                if sha256_file(target / record["name"]) != record["sha256"]:
                    raise FormatError(f"hash do runtime restaurado diverge: {record['name']}")
        except BaseException as error:
            rollback_errors = []
            for final, previous in reversed(attempted):
                try:
                    if previous.exists():
                        os.replace(previous, final)
                    else:
                        final.unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(str(rollback_error))
            if rollback_errors:
                raise FormatError(f"rollback incompleto; preserve a recuperacao em {staging}: {rollback_errors}") from error
            raise
    return {"tool_version": __version__, "generated_at": datetime.now().astimezone().isoformat(),
            "root": str(root), "client_root": str(client_root), "archive": str(archive),
            "archive_sha256": sha256_file(archive), "files": records,
            "canonical_baseline_modified": False, "passed": True}
