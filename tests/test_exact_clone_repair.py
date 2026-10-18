from __future__ import annotations

import unittest

from nwoassets.exact_clone_repair import clone_xml_definitions


class ExactCloneRepairTests(unittest.TestCase):
    def test_xml_definition_with_children_is_cloned_exactly(self):
        source = (
            b'<?xml version="1.0"?>\n<items>\n'
            b'\t<item id="10" article="a" name="Ramp">\n'
            b'\t\t<attribute key="floorchange" value="north" />\n'
            b'\t</item>\n</items>\n'
        )
        result, report = clone_xml_definitions(source, {20: 10})
        self.assertIn(b'<item id="20" article="a" name="Ramp">', result)
        self.assertEqual(result.count(b'key="floorchange"'), 2)
        self.assertEqual(report["target_definitions_written"], 1)

        second, second_report = clone_xml_definitions(result, {20: 10})
        self.assertEqual(second, result)
        self.assertEqual(second_report["target_definitions_written"], 0)
        self.assertEqual(second_report["target_definitions_already_exact"], 1)

    def test_xml_definition_from_range_is_cloned_as_individual_items(self):
        source = (
            b'<?xml version="1.0"?>\n<items>\n'
            b'\t<item fromid="10" toid="11" article="a" name="Wall" />\n'
            b'</items>\n'
        )
        result, report = clone_xml_definitions(source, {20: 10, 21: 11})
        self.assertIn(b'<item id="20" article="a" name="Wall" />', result)
        self.assertIn(b'<item id="21" article="a" name="Wall" />', result)
        self.assertEqual(report["source_definitions"], 2)
        self.assertEqual(report["target_definitions_written"], 2)


if __name__ == "__main__":
    unittest.main()
