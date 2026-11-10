"""Import the authoritative server map into the tool's operational copy."""
from pathlib import Path
import os
import shutil

from .content import sha256_file
from .errors import FormatError
from .pipeline import validate_root
from .versioning import create_version, require_asset_layout


def align_server_world(root: Path) -> dict[str, object]:
    root = root.resolve()
    layout = require_asset_layout(root)
    source = root.parent / 'Server-Data-Nwo/data/world/mapanovo.otbm'
    target = layout['world'] / 'mapanovo.otbm'
    if not source.is_file() or not target.is_file():
        raise FormatError('mapa oficial ou copia operacional ausente')
    checksum = sha256_file(source)
    before = sha256_file(target)
    report = {'source': str(source), 'target': str(target), 'source_sha256': checksum,
              'previous_sha256': before, 'changed': before != checksum, 'passed': False}
    if before == checksum:
        report['passed'] = True
        return report
    pending = target.with_name('.mapanovo.nwoassets.pending.otbm')
    backup = target.with_name('.mapanovo.nwoassets.backup.otbm')
    if pending.exists() or backup.exists():
        raise FormatError('alinhamento bloqueado por temporarios pendentes')
    validation = validate_root(root, deep_spr=True, world_directory=source.parent)
    if not validation['passed']:
        raise FormatError(f"mapa oficial/baseline reprovaram: {validation['errors']}")
    version = create_version(root, world_file=source)
    report['version'] = version
    published = False
    try:
        shutil.copy2(source, pending)
        if sha256_file(pending) != checksum or sha256_file(source) != checksum:
            raise FormatError('mapa oficial mudou durante a preparacao')
        if sha256_file(target) != before:
            raise FormatError('copia operacional mudou durante a preparacao')
        os.replace(target, backup)
        os.replace(pending, target)
        published = True
        validation = validate_root(root, deep_spr=True)
        if not validation['passed']:
            raise FormatError(f"validacao final reprovou: {validation['errors']}")
        if sha256_file(source) != checksum or sha256_file(target) != checksum:
            raise FormatError('mapa mudou durante a validacao final')
        backup.unlink()
        report.update(passed=True, committed=True, sha256=checksum)
        return report
    except BaseException:
        if backup.exists():
            # Never overwrite an external edit during rollback.
            if published and sha256_file(target) != checksum:
                raise FormatError(f'alteracao externa detectada; backup preservado em {backup}')
            os.replace(backup, target)
        raise
    finally:
        if pending.exists():
            pending.unlink()
