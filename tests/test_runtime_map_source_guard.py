import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from nwoassets.errors import FormatError
from nwoassets.runtime_sync import sync_runtime_assets
from test_runtime_sync import RuntimeSyncTests


class MapSourceGuardTest(unittest.TestCase):
    def test_missing_or_changed_official_map_blocks_before_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_,_=RuntimeSyncTests().make_workspace(folder)
            official=Path(folder)/'Server-Data-Nwo/data/world/mapanovo.otbm'
            with patch('nwoassets.runtime_sync.validate_root') as validate:
                with self.assertRaises(FormatError):
                    sync_runtime_assets(root,expected_server_map_hash='0'*64)
                official.unlink()
                with self.assertRaises(FormatError):
                    sync_runtime_assets(root,expected_server_map_hash='0'*64)
                validate.assert_not_called()

    def test_change_during_validation_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_,_=RuntimeSyncTests().make_workspace(folder)
            official=Path(folder)/'Server-Data-Nwo/data/world/mapanovo.otbm'
            expected=hashlib.sha256(official.read_bytes()).hexdigest()
            def validate(*args,**kwargs):
                official.write_bytes(b'new-user-map')
                return {'passed':True,'errors':[]}
            with patch('nwoassets.runtime_sync.validate_root',side_effect=validate):
                with self.assertRaises(FormatError):sync_runtime_assets(root,expected_server_map_hash=expected)
            self.assertEqual(official.read_bytes(),b'new-user-map')


if __name__=='__main__':unittest.main()
