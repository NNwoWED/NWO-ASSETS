import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

from nwoassets.client_runtime_restore import restore_client_runtime
from nwoassets.errors import FormatError
from nwoassets.runtime_sync import _runtime_paths
import test_runtime_sync as runtime_fixture


class ClientArchiveRestoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root, _, _ = runtime_fixture.RuntimeSyncTests().make_workspace(self.directory.name)
        self.client = self.root.parent / 'nwo-otclient-mehah-4.0'
        self.target = self.client / 'data/things/860'
        self.archive = self.client / 'data/things/860.rar'
        self.payloads = {'Tibia.dat': b'branch-main-dat', 'Tibia.spr': b'branch-main-spr', 'Tibia.otfi': b'branch-main-otfi'}
        self.entries = ['860'] + ['860/' + n for n in self.payloads]
        self.extracted = False
        self.ran = []

    def rar(self, executable, args):
        self.ran.append(args[0])
        if args[0] == 'lb':
            return ('\n'.join(self.entries) + '\n').encode()
        if args[0] == 'x':
            self.extracted = True
            destination = Path(args[-1]) / '860'
            destination.mkdir()
            for name, payload in self.payloads.items():
                (destination / name).write_bytes(payload)
        return b''

    def restore(self, **overrides):
        kwargs = dict(client_root=self.client, archive=self.archive,
                      dat_sha256=hashlib.sha256(self.payloads['Tibia.dat']).hexdigest(),
                      spr_sha256=hashlib.sha256(self.payloads['Tibia.spr']).hexdigest())
        kwargs.update(overrides)
        with patch('nwoassets.client_runtime_restore.validate_root', return_value={'passed': True}), \
             patch('nwoassets.client_runtime_restore.find_rar', return_value=Path('rar.exe')), \
             patch('nwoassets.client_runtime_restore._run_rar', side_effect=self.rar):
            return restore_client_runtime(self.root, **kwargs)

    def test_verified_archive_restores_client_only(self):
        canonical = (self.root / 'assets/860/Tibia.spr').read_bytes()
        report = self.restore()
        self.assertTrue(report['passed'])
        self.assertEqual(self.ran[:2], ['t', 'lb'])
        for name, payload in self.payloads.items():
            self.assertEqual((self.target / name).read_bytes(), payload)
        self.assertEqual((self.root / 'assets/860/Tibia.spr').read_bytes(), canonical)
        self.assertEqual(self.archive.read_bytes(), b'old-rar')

    def test_bad_hash_never_changes_live_client(self):
        before = (self.target / 'Tibia.dat').read_bytes()
        with self.assertRaises(FormatError):
            self.restore(dat_sha256='0' * 64)
        self.assertEqual((self.target / 'Tibia.dat').read_bytes(), before)

    def test_path_escape_is_rejected_before_extraction(self):
        for bad in ['860/../outside', 'C:/outside', '/outside', '860/extra.exe']:
            self.entries = ['860/Tibia.dat', '860/Tibia.spr', '860/Tibia.otfi', bad]
            with self.assertRaises(FormatError):
                self.restore()
            self.assertFalse(self.extracted)

    def test_partial_install_failure_restores_all_prior_files(self):
        previous = {p.name: p.read_bytes() for p in self.target.iterdir()}
        original = os.replace
        failed = False
        def replace(source, destination):
            nonlocal failed
            if not failed and Path(source).name == 'Tibia.spr' and 'extracted' in Path(source).parts:
                failed = True
                raise OSError('simulated install failure')
            return original(source, destination)
        with patch('nwoassets.client_runtime_restore.os.replace', side_effect=replace):
            with self.assertRaises(OSError):
                self.restore()
        for name, payload in previous.items():
            self.assertEqual((self.target / name).read_bytes(), payload)

    def test_critical_rollback_failure_keeps_recovery_files(self):
        original = os.replace
        def replace(source, destination):
            source = Path(source)
            if source.name == 'Tibia.spr' and 'extracted' in source.parts:
                raise OSError('install fail')
            if source.name == 'Tibia.dat' and 'backup' in source.parts:
                raise OSError('rollback fail')
            return original(source, destination)
        with patch('nwoassets.client_runtime_restore.os.replace', side_effect=replace):
            with self.assertRaisesRegex(FormatError, 'rollback incompleto'):
                self.restore()
        backups = list((self.root / 'reports').glob('.client-runtime-restore-*/backup/Tibia.dat'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'old-dat')

    def test_explicit_worktree_destination_does_not_select_main(self):
        worktree = self.root.parent / 'pc-worktree'
        (worktree / 'data/things/860').mkdir(parents=True)
        _, targets, client_860, archive, *_ = _runtime_paths(self.root, worktree)
        self.assertEqual(client_860, worktree / 'data/things/860')
        self.assertEqual(targets['Tibia.spr'], worktree / 'data/things/860/Tibia.spr')
        self.assertEqual(archive, worktree / 'data/things/860.rar')
        self.assertNotEqual(targets['Tibia.spr'], self.target / 'Tibia.spr')


if __name__ == '__main__':
    unittest.main()
