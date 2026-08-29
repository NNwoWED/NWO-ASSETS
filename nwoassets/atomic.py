from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
from typing import BinaryIO, Iterator

from .errors import FormatError


@contextmanager
def atomic_binary_output(path: Path) -> Iterator[BinaryIO]:
    """Write a file through a sibling temporary and publish it atomically."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.nwoassets.tmp")
    if temporary.exists():
        raise FormatError(f"arquivo temporário já existe: {temporary}")

    stream: BinaryIO | None = None
    try:
        stream = temporary.open("xb")
        yield stream
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        stream = None
        os.replace(temporary, path)
    except BaseException:
        if stream is not None:
            stream.close()
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
