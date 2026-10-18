from __future__ import annotations

from .errors import FormatError
from .png import PngImage, split_tiles_bottom_right_first


def split_appearance_sheet(
    image: PngImage,
    *,
    sprite_size: int,
    width: int,
    height: int,
    layers: int = 1,
    pattern_x: int = 1,
    pattern_y: int = 1,
    pattern_z: int = 1,
    frames: int = 1,
) -> tuple[tuple[bytes, ...], ...]:
    """Split an exported ThingType sheet in DAT sprite order."""

    dimensions = (width, height, layers, pattern_x, pattern_y, pattern_z, frames)
    if any(value < 1 or value > 255 for value in dimensions):
        raise FormatError("dimensoes/patterns/frames devem estar em 1..255")
    cell_width = width * sprite_size
    cell_height = height * sprite_size
    expected_width = cell_width * layers * pattern_x
    expected_height = cell_height * frames * pattern_y * pattern_z
    if (image.width, image.height) != (expected_width, expected_height):
        raise FormatError(
            f"folha {image.width}x{image.height}; layout exige "
            f"{expected_width}x{expected_height}"
        )

    source_stride = image.width * 4
    groups: list[tuple[bytes, ...]] = []
    for frame in range(frames):
        for z in range(pattern_z):
            for y in range(pattern_y):
                for x in range(pattern_x):
                    for layer in range(layers):
                        origin_x = cell_width * (x + pattern_x * layer)
                        origin_y = cell_height * (
                            y + pattern_y * frame + pattern_y * frames * z
                        )
                        rgba = bytearray(cell_width * cell_height * 4)
                        destination_stride = cell_width * 4
                        for row in range(cell_height):
                            source_start = (
                                (origin_y + row) * source_stride + origin_x * 4
                            )
                            destination_start = row * destination_stride
                            rgba[
                                destination_start : destination_start + destination_stride
                            ] = image.rgba[
                                source_start : source_start + destination_stride
                            ]
                        groups.append(
                            tuple(
                                split_tiles_bottom_right_first(
                                    PngImage(cell_width, cell_height, bytes(rgba)),
                                    sprite_size,
                                )
                            )
                        )
    return tuple(groups)


def split_flattened_z_sheet(
    image: PngImage,
    *,
    sprite_size: int,
    width: int,
    height: int,
    layers: int,
    pattern_x: int,
    pattern_y: int,
    pattern_z: int,
    frames: int,
) -> tuple[tuple[bytes, ...], ...]:
    """Read Object Builder sheets that flatten pattern Z into columns.

    The physical grid stores ``x + pattern_x * z`` horizontally and Y/frame
    vertically. Returned groups still follow DAT order: frame, Z, Y, X, layer.
    """

    dimensions = (width, height, layers, pattern_x, pattern_y, pattern_z, frames)
    if any(value < 1 or value > 255 for value in dimensions):
        raise FormatError("dimensoes/patterns/frames devem estar em 1..255")
    cell_width = width * sprite_size
    cell_height = height * sprite_size
    expected_width = cell_width * layers * pattern_x * pattern_z
    expected_height = cell_height * pattern_y * frames
    if (image.width, image.height) != (expected_width, expected_height):
        raise FormatError(
            f"folha Object Builder {image.width}x{image.height}; layout exige "
            f"{expected_width}x{expected_height}"
        )

    source_stride = image.width * 4
    groups: list[tuple[bytes, ...]] = []
    for frame in range(frames):
        for z in range(pattern_z):
            for y in range(pattern_y):
                for x in range(pattern_x):
                    for layer in range(layers):
                        origin_x = cell_width * (
                            x + pattern_x * z + pattern_x * pattern_z * layer
                        )
                        origin_y = cell_height * (y + pattern_y * frame)
                        rgba = bytearray(cell_width * cell_height * 4)
                        destination_stride = cell_width * 4
                        for row in range(cell_height):
                            source_start = (
                                (origin_y + row) * source_stride + origin_x * 4
                            )
                            destination_start = row * destination_stride
                            rgba[
                                destination_start : destination_start + destination_stride
                            ] = image.rgba[
                                source_start : source_start + destination_stride
                            ]
                        groups.append(
                            tuple(
                                split_tiles_bottom_right_first(
                                    PngImage(cell_width, cell_height, bytes(rgba)),
                                    sprite_size,
                                )
                            )
                        )
    return tuple(groups)
