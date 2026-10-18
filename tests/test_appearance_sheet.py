from __future__ import annotations

import unittest

from nwoassets.appearance_sheet import split_appearance_sheet, split_flattened_z_sheet
from nwoassets.png import PngImage


class AppearanceSheetTests(unittest.TestCase):
    def test_patterns_are_grouped_before_bottom_right_tile_order(self):
        rgba = bytearray(128 * 64 * 4)
        colors = (10, 20, 30, 40, 50, 60, 70, 80)
        for index, red in enumerate(colors):
            x = (index % 4) * 32
            y = (index // 4) * 32
            tile = bytes((red, 0, 0, 255)) * (32 * 32)
            for row in range(32):
                source = row * 32 * 4
                target = ((y + row) * 128 + x) * 4
                rgba[target:target + 32 * 4] = tile[source:source + 32 * 4]
        groups = split_appearance_sheet(
            PngImage(128, 64, bytes(rgba)),
            sprite_size=32,
            width=2,
            height=2,
            pattern_x=2,
        )
        self.assertEqual(
            [[tile[0] for tile in group] for group in groups],
            [[60, 50, 20, 10], [80, 70, 40, 30]],
        )

    def test_object_builder_z_columns_are_returned_in_dat_order(self):
        rgba = bytearray(128 * 64 * 4)
        colors = (10, 20, 30, 40, 50, 60, 70, 80)
        for index, red in enumerate(colors):
            x = (index % 4) * 32
            y = (index // 4) * 32
            tile = bytes((red, 0, 0, 255)) * (32 * 32)
            for row in range(32):
                source = row * 32 * 4
                target = ((y + row) * 128 + x) * 4
                rgba[target:target + 32 * 4] = tile[source:source + 32 * 4]
        groups = split_flattened_z_sheet(
            PngImage(128, 64, bytes(rgba)),
            sprite_size=32,
            width=1,
            height=1,
            layers=1,
            pattern_x=2,
            pattern_y=2,
            pattern_z=2,
            frames=1,
        )
        self.assertEqual([group[0][0] for group in groups], [10, 20, 50, 60, 30, 40, 70, 80])


if __name__ == "__main__":
    unittest.main()
