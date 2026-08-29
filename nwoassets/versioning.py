from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import shutil
import subprocess
import zipfile

from . import __version__
from .atomic import atomic_binary_output
from .content import sha256_file
from .errors import FormatError


RAR_CANDIDATES = (
    Path(r"C:\Program Files\WinRAR\rar.exe"),
    Path(r"C:\Program Files (x86)\WinRAR\rar.exe"),
)


def require_asset_layout(root: Path) -> dict[str, Path]:
    root = root.resolve()
    asset_root = root / "assets"
    paths = {
        "root": asset_root,
        "860": asset_root / "860",
        "items": asset_root / "items",
        "world": asset_root / "world",
    }
    missing = [str(path) for name, path in paths.items() if name != "root" and not path.is_dir()]
    if not asset_root.is_dir() or missing:
        raise FormatError(
            f"estrutura obrigatória ausente em {asset_root}; esperado assets/860, "
            f"assets/items e assets/world (ausentes: {missing})"
        )
    return paths


def find_rar() -> Path:
    discovered = shutil.which("rar")
    if discovered:
        return Path(discovered).resolve()
    for candidate in RAR_CANDIDATES:
        if candidate.is_file():
            return candidate.resolve()
    raise FormatError("rar.exe não encontrado; instale o WinRAR antes de versionar")


def _run_rar(rar: Path, arguments: list[str], cwd: Path | None = None) -> bytes:
    result = subprocess.run(
        [str(rar), *arguments],
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        details = result.stdout.decode("utf-8", errors="replace")[-2000:]
        raise FormatError(
            f"rar.exe falhou com exit code {result.returncode}: {details.strip()}"
        )
    return result.stdout


def _archive_rar(rar: Path, source: Path, files: list[Path], destination: Path) -> None:
    if not files:
        raise FormatError(f"nenhum arquivo selecionado para {destination.name}")
    relative = [str(path.relative_to(source)) for path in files]
    _run_rar(
        rar,
        ["a", "-ma5", "-m3", "-idq", str(destination), *relative],
        cwd=source,
    )
    if not destination.is_file():
        raise FormatError(f"rar.exe não criou {destination}")
    _run_rar(rar, ["t", "-idq", str(destination)])
    listed = _run_rar(rar, ["lb", str(destination)]).decode(
        "utf-8", errors="replace"
    )
    actual = {
        line.strip().replace("/", "\\").casefold()
        for line in listed.splitlines()
        if line.strip()
    }
    expected = {name.replace("/", "\\").casefold() for name in relative}
    if actual != expected:
        raise FormatError(
            f"conteúdo inesperado em {destination.name}: "
            f"esperado={sorted(expected)}, encontrado={sorted(actual)}"
        )


def _archive_world(map_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(
        destination,
        "x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        archive.write(map_path, arcname=map_path.name)
    with zipfile.ZipFile(destination) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].filename != map_path.name:
            raise FormatError(f"{destination}: deve conter somente {map_path.name}")
        with archive.open(entries[0]) as stream:
            import hashlib

            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest().upper() != sha256_file(map_path):
            raise FormatError(f"{destination}: hash do OTBM compactado diverge da origem")


def create_version(root: Path) -> dict[str, object]:
    root = root.resolve()
    layout = require_asset_layout(root)
    rar = find_rar()
    files_860 = sorted(path for path in layout["860"].rglob("*") if path.is_file())
    files_items = sorted(
        path
        for path in layout["items"].rglob("*")
        if path.is_file() and path.suffix.casefold() != ".xml"
    )
    maps = sorted(layout["world"].glob("*.otbm"))
    reserved = [
        path
        for path in [*files_860, *files_items]
        if ".nwoassets." in path.name.casefold()
    ]
    if reserved:
        raise FormatError(
            "versionamento bloqueado por temporários pendentes: "
            + ", ".join(str(path) for path in reserved)
        )
    if len(maps) != 1:
        raise FormatError(f"versionamento exige um OTBM; encontrados {len(maps)}")

    version_id = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    version_root = root / "versions" / version_id
    if version_root.exists():
        raise FormatError(f"versão já existe: {version_root}")
    version_root.mkdir(parents=True)
    archives = {
        "860": version_root / "860.rar",
        "items": version_root / "items.rar",
        "world": version_root / "world.zip",
    }
    try:
        _archive_rar(rar, layout["860"], files_860, archives["860"])
        _archive_rar(rar, layout["items"], files_items, archives["items"])
        _archive_world(maps[0], archives["world"])
        source_files = files_860 + files_items + [maps[0]]
        report: dict[str, object] = {
            "tool_version": __version__,
            "version_id": version_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "root": str(version_root),
            "rar_executable": str(rar),
            "sources": [
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in source_files
            ],
            "archives": {
                name: {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for name, path in archives.items()
            },
            "items_xml_excluded": True,
            "world_entries": [maps[0].name],
            "passed": True,
        }
        payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with atomic_binary_output(version_root / "version.json") as stream:
            stream.write(payload)
        return report
    except BaseException:
        shutil.rmtree(version_root, ignore_errors=True)
        raise
