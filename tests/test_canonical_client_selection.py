from pathlib import Path
import tempfile
import unittest

from nwoassets.pipeline import _single
from nwoassets.errors import FormatError


class CanonicalClientSelectionTest(unittest.TestCase):
    def test_work_backups_do_not_replace_operational_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in ['assets/860/Tibia.otfi', 'assets/items/items.otb',
                             'work/main-before/860/Tibia.otfi', 'work/main-before/items/items.otb']:
                path = root/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            self.assertEqual(_single(root, 'Tibia.otfi'), root/'assets/860/Tibia.otfi')
            self.assertEqual(_single(root, 'items.otb'), root/'assets/items/items.otb')

    def test_missing_canonical_input_does_not_use_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'assets/860').mkdir(parents=True)
            backup = root/'work/Tibia.otfi'
            backup.parent.mkdir()
            backup.write_bytes(b'fixture')
            with self.assertRaises(FormatError):
                _single(root, 'Tibia.otfi')


if __name__ == '__main__':
    unittest.main()
