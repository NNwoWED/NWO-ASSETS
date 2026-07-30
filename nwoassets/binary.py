from __future__ import annotations

import struct

from .errors import FormatError


class BinaryReader:
    def __init__(self, data: bytes, *, source: str = "<bytes>") -> None:
        self.data = data
        self.source = source
        self.position = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.position

    def _take(self, size: int) -> bytes:
        end = self.position + size
        if size < 0 or end > len(self.data):
            raise FormatError(
                f"{self.source}: leitura de {size} bytes fora do arquivo "
                f"no offset {self.position}"
            )
        value = self.data[self.position:end]
        self.position = end
        return value

    def u8(self) -> int:
        return self._take(1)[0]

    def i8(self) -> int:
        return struct.unpack("<b", self._take(1))[0]

    def u16(self) -> int:
        return struct.unpack("<H", self._take(2))[0]

    def i16(self) -> int:
        return struct.unpack("<h", self._take(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def bytes(self, size: int) -> bytes:
        return self._take(size)

    def skip(self, size: int) -> None:
        self._take(size)

