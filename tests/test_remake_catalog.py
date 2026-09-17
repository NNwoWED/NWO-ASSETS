import unittest

from nwoassets.remake_catalog import remove_remake_catalog_entries


class RemakeCatalogTests(unittest.TestCase):
    def test_removes_only_target_rows_in_each_table(self):
        source = (
            b'ITEMS_BYCID = {\r\n'
            b'[200] = {serverid = "10051", },\r\n'
            b'[201] = {serverid = "10091", },\r\n'
            b'}\r\n'
            b'ITEMS_BYNAME = {\r\n'
            b'["old"] = {serverid = "10051", },\r\n'
            b'["keep"] = {serverid = "10091", },\r\n'
            b'}\r\n'
            b'ITEMS_BYSERVERID = {\r\n'
            b'[10051] = {name = "old"},\r\n'
            b'[10091] = {name = "keep"},\r\n'
            b'}\r\n'
        )
        updated, counts = remove_remake_catalog_entries(source, {10051})
        self.assertEqual(counts, {
            "ITEMS_BYCID": 1,
            "ITEMS_BYNAME": 1,
            "ITEMS_BYSERVERID": 1,
        })
        self.assertNotIn(b"10051", updated)
        self.assertEqual(updated.count(b"10091"), 3)
        self.assertIn(b"\r\n", updated)


if __name__ == "__main__":
    unittest.main()
