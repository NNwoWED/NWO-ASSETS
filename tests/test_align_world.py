from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nwoassets.align_world import align_server_world
from nwoassets.errors import FormatError


class AlignWorldTest(unittest.TestCase):
    def test_client_baseline_ignores_work_backups(self):
        from nwoassets.pipeline import _single
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);canonical=root/'assets/860/Tibia.otfi';copy=root/'work/old/860/Tibia.otfi'
            canonical.parent.mkdir(parents=True);copy.parent.mkdir(parents=True)
            canonical.write_bytes(b'canonical');copy.write_bytes(b'old')
            self.assertEqual(_single(root,'Tibia.otfi'),canonical)

    def workspace(self, directory):
        root = Path(directory) / 'NWO-ASSETS'
        for folder in ('860', 'items', 'world'):
            (root / 'assets' / folder).mkdir(parents=True)
        source = root.parent / 'Server-Data-Nwo/data/world/mapanovo.otbm'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'official map')
        target = root / 'assets/world/mapanovo.otbm'
        target.write_bytes(b'old operational copy')
        return root, source, target

    @patch('nwoassets.align_world.validate_root', return_value={'passed': True})
    @patch('nwoassets.align_world.create_version', return_value={'passed': True})
    def test_versions_official_map_before_aligning_and_is_idempotent(self, version, validate):
        with tempfile.TemporaryDirectory() as directory:
            root, source, target = self.workspace(directory)
            def snapshot(path, *, world_file):
                self.assertEqual(world_file, source)
                self.assertEqual(target.read_bytes(), b'old operational copy')
                return {'passed': True}
            version.side_effect = snapshot
            report = align_server_world(root)
            self.assertTrue(report['committed'])
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(validate.call_args_list[0].kwargs['world_directory'], source.parent)
            self.assertFalse(align_server_world(root)['changed'])
            self.assertEqual(version.call_count, 1)

    @patch('nwoassets.align_world.validate_root', return_value={'passed': True})
    @patch('nwoassets.align_world.create_version', side_effect=FormatError('archive failed'))
    def test_archive_failure_keeps_both_maps(self, version, validate):
        with tempfile.TemporaryDirectory() as directory:
            root, source, target = self.workspace(directory)
            with self.assertRaises(FormatError):
                align_server_world(root)
            self.assertEqual(source.read_bytes(), b'official map')
            self.assertEqual(target.read_bytes(), b'old operational copy')

    @patch('nwoassets.align_world.create_version', return_value={'passed': True})
    def test_failed_final_validation_restores_operational_copy(self, version):
        with tempfile.TemporaryDirectory() as directory:
            root, source, target = self.workspace(directory)
            with patch('nwoassets.align_world.validate_root', side_effect=[
                {'passed': True}, {'passed': False, 'errors': ['invalid']}
            ]), self.assertRaises(FormatError):
                align_server_world(root)
            self.assertEqual(target.read_bytes(), b'old operational copy')
            self.assertEqual(source.read_bytes(), b'official map')

    @patch('nwoassets.align_world.validate_root', return_value={'passed': True})
    def test_source_change_during_version_is_rejected(self, validate):
        with tempfile.TemporaryDirectory() as directory:
            root, source, target = self.workspace(directory)
            def changed(*args, **kwargs):
                source.write_bytes(b'external new official map')
                return {'passed': True}
            with patch('nwoassets.align_world.create_version', side_effect=changed), self.assertRaises(FormatError):
                align_server_world(root)
            self.assertEqual(target.read_bytes(), b'old operational copy')
            self.assertEqual(source.read_bytes(), b'external new official map')

    @patch('nwoassets.align_world.create_version', return_value={'passed': True})
    def test_external_target_edit_during_validation_is_preserved(self, version):
        with tempfile.TemporaryDirectory() as directory:
            root, source, target = self.workspace(directory)
            def changed(*args, **kwargs):
                if 'world_directory' not in kwargs:
                    target.write_bytes(b'external working edit')
                return {'passed': True}
            with patch('nwoassets.align_world.validate_root', side_effect=changed), self.assertRaises(FormatError):
                align_server_world(root)
            self.assertEqual(target.read_bytes(), b'external working edit')
            self.assertEqual(target.with_name('.mapanovo.nwoassets.backup.otbm').read_bytes(), b'old operational copy')


if __name__ == '__main__':
    unittest.main()
