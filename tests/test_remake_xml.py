from __future__ import annotations

import unittest

from nwoassets.errors import FormatError
from nwoassets.remake_xml import replace_remake_xml


class RemakeXmlTests(unittest.TestCase):
    def test_replaces_names_without_touching_unrelated_items(self) -> None:
        original = (
            b'<?xml version="1.0" encoding="UTF-8"?>\r\n<items>\r\n'
            b'\t<item fromid="100" toid="101" name="Source" />\r\n'
            b'\t<item id="200" name="Old" />\r\n'
            b'\t<item id="201" name="Old 2" />\r\n'
            b'\t<item id="300" name="Keep" />\r\n'
            b'</items>\r\n'
        )
        result, summary = replace_remake_xml(original, {200: 100, 201: 101})
        self.assertIn(b'<item id="200" name="Source" />', result)
        self.assertIn(b'<item id="201" name="Source" />', result)
        self.assertNotIn(b'name="Old"', result)
        self.assertIn(b'<item id="300" name="Keep" />', result)
        self.assertEqual(summary["target_definitions_written"], 2)

    def test_removes_name_when_source_has_no_definition(self) -> None:
        original = b'<items>\n\t<item id="200" name="Old" />\n</items>\n'
        result, summary = replace_remake_xml(original, {200: 100})
        self.assertNotIn(b'name="Old"', result)
        self.assertEqual(summary["target_definitions_written"], 0)

    def test_rejects_partial_range(self) -> None:
        original = b'<items>\n\t<item id="100" name="Source" />\n\t<item fromid="200" toid="201" name="Old" />\n</items>\n'
        with self.assertRaises(FormatError):
            replace_remake_xml(original, {200: 100})


if __name__ == "__main__":
    unittest.main()
