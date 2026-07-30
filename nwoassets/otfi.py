from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

from .errors import FormatError


@dataclass(frozen=True)
class OtfiConfig:
    extended: bool
    transparency: bool
    frame_durations: bool
    frame_groups: bool
    metadata_file: str
    sprites_file: str
    sprite_size: int
    sprite_data_size: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_PAIR = re.compile(r"^\s*([a-zA-Z0-9-]+)\s*:\s*(.*?)\s*$")


def parse_otfi(path: Path) -> OtfiConfig:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise FormatError(f"{path}: não foi possível ler OTFI: {exc}") from exc

    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _PAIR.match(line)
        if match:
            values[match.group(1).lower()] = match.group(2)

    required = {
        "extended",
        "transparency",
        "frame-durations",
        "frame-groups",
        "metadata-file",
        "sprites-file",
        "sprite-size",
        "sprite-data-size",
    }
    missing = sorted(required - values.keys())
    if missing:
        raise FormatError(f"{path}: chaves OTFI ausentes: {', '.join(missing)}")

    def boolean(name: str) -> bool:
        value = values[name].lower()
        if value not in {"true", "false"}:
            raise FormatError(f"{path}: booleano inválido em {name}: {value}")
        return value == "true"

    try:
        return OtfiConfig(
            extended=boolean("extended"),
            transparency=boolean("transparency"),
            frame_durations=boolean("frame-durations"),
            frame_groups=boolean("frame-groups"),
            metadata_file=values["metadata-file"],
            sprites_file=values["sprites-file"],
            sprite_size=int(values["sprite-size"]),
            sprite_data_size=int(values["sprite-data-size"]),
        )
    except ValueError as exc:
        raise FormatError(f"{path}: valor numérico inválido: {exc}") from exc

