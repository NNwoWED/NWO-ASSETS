from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from nwoassets.exporter import compose_appearance_sheet
from nwoassets.png import PngImage, read_png_rgba, write_png_rgba
from nwoassets.roundtrip import DatAppearance


def solid_tile(red: int, green: int, blue: int, alpha: int = 255) -> bytes:
    return bytes((red, green, blue, alpha)) * (32 * 32)


def pixel(image: PngImage, x: int, y: int) -> tuple[int, int, int, int]:
    start = (y * image.width + x) * 4
    return tuple(image.rgba[start : start + 4])  # type: ignore[return-value]


class PngWriterTests(unittest.TestCase):
    def test_roundtrips_exported_rgba_png(self) -> None:
        rgba = bytes((10, 20, 30, 0, 40, 50, 60, 255))
        image = PngImage(2, 1, rgba)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.png"
            write_png_rgba(path, image)
            decoded = read_png_rgba(path)
        self.assertEqual(decoded, image)


class AppearanceCompositionTests(unittest.TestCase):
    def test_accepts_zero_sprite_as_transparent_tile(self) -> None:
        appearance = DatAppearance(1, 1, None, 1, 1, 1, 1, 1, (0,))
        image = compose_appearance_sheet(
            appearance,
            {0: bytes(32 * 32 * 4)},
        )
        self.assertEqual((image.width, image.height), (32, 32))
        self.assertEqual(pixel(image, 0, 0), (0, 0, 0, 0))

    def test_reverses_multitile_storage_into_visual_order(self) -> None:
        appearance = DatAppearance(2, 1, 64, 1, 1, 1, 1, 1, (1, 2))
        image = compose_appearance_sheet(
            appearance,
            {1: solid_tile(255, 0, 0), 2: solid_tile(0, 255, 0)},
        )
        self.assertEqual((image.width, image.height), (64, 32))
        self.assertEqual(pixel(image, 0, 0), (0, 255, 0, 255))
        self.assertEqual(pixel(image, 32, 0), (255, 0, 0, 255))

    def test_places_layers_horizontally_and_frames_vertically(self) -> None:
        appearance = DatAppearance(1, 1, None, 2, 1, 1, 1, 2, (1, 2, 3, 4))
        image = compose_appearance_sheet(
            appearance,
            {
                1: solid_tile(255, 0, 0),
                2: solid_tile(0, 255, 0),
                3: solid_tile(0, 0, 255),
                4: solid_tile(255, 255, 0),
            },
        )
        self.assertEqual((image.width, image.height), (64, 64))
        self.assertEqual(pixel(image, 0, 0), (255, 0, 0, 255))
        self.assertEqual(pixel(image, 32, 0), (0, 255, 0, 255))
        self.assertEqual(pixel(image, 0, 32), (0, 0, 255, 255))
        self.assertEqual(pixel(image, 32, 32), (255, 255, 0, 255))


if __name__ == "__main__":
    unittest.main()
