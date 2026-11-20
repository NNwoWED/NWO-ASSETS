"""Adopt the user-authoritative server map through NWO-ASSETS publication.

Only the tool's operational map is replaced. The official server file is never
written. Its tested ZIP becomes a readonly history input to publish_map.
"""
from pathlib import Path
import hashlib
import json
import os
import zipfile

from nwoassets.versioning import _archive_world
from nwoassets.map_edit import inspect_map
from nwoassets.map_publish import publish_map, _extract

ROOT = Path.cwd()
SERVER = ROOT.parent / 'Server-Data-Nwo/data/world'
OFFICIAL = SERVER / 'mapanovo.otbm'
OPERATIONAL = ROOT / 'assets/world/mapanovo.otbm'
REPORT = ROOT / 'reports/adopt-current-server-map-chiyo-20261120.json'


def checksum(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def main():
    source_hash = checksum(OFFICIAL)
    old_hash = checksum(OPERATIONAL)
    print('Inspecting official server map', source_hash, flush=True)
    inspection = inspect_map(OFFICIAL)
    assert inspection['sha256'] == source_hash
    assert inspection['version'] == 2
    archive = ROOT / 'drafts' / ('official-server-map-' + source_hash + '.zip')
    if not archive.exists():
        _archive_world(OFFICIAL, archive)
    with zipfile.ZipFile(archive) as zf:
        assert zf.namelist() == ['mapanovo.otbm'] and zf.testzip() is None
        with zf.open('mapanovo.otbm') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == source_hash
    cache = ROOT / 'drafts/history' / (source_hash + '.baseline')
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        pending = cache.with_suffix('.adopt-pending')
        assert not pending.exists()
        _extract(archive, 'mapanovo.otbm', pending)
        assert checksum(pending) == source_hash
        os.replace(pending, cache)
    assert checksum(cache) == source_hash

    def source_unchanged(_):
        assert checksum(OFFICIAL) == source_hash, 'Official map changed; publication cancelled'

    last_progress = [-1]
    def progress(fraction, message):
        percent = int(fraction * 100)
        if percent != last_progress[0]:
            print(f'{percent}% {message}', flush=True)
            last_progress[0] = percent

    result = publish_map(
        ROOT, cache, {}, expected_hash=old_hash, source_hash=source_hash,
        before_replace=source_unchanged,
        progress=progress,
        journal_path=ROOT / 'reports/journal-adopt-current-server-map-chiyo-20261120.json',
        journal_context={'operation': 'adopt user-authoritative server map', 'source': str(OFFICIAL)},
    )
    assert result['passed'] and result['committed'] and result['sha256'] == source_hash
    assert checksum(OFFICIAL) == source_hash
    report = {'passed': True, 'committed': True, 'source': str(OFFICIAL),
              'source_sha256': source_hash, 'previous_operational_sha256': old_hash,
              'source_preserved': True, 'source_zip_verified': True,
              'source_inspection': inspection, 'publication': result}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print('Official map adopted and deeply validated.', flush=True)


if __name__ == '__main__':
    main()
