from __future__ import annotations

from dataclasses import asdict, dataclass

from .errors import ProfileError


@dataclass(frozen=True)
class ClientProfile:
    key: str
    client_version: int
    label: str
    dat_signature: int
    spr_signature: int
    metadata_reader: int
    otb_version_hint: str

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["dat_signature"] = f"0x{self.dat_signature:08X}"
        result["spr_signature"] = f"0x{self.spr_signature:08X}"
        return result


TIBIA_860_V2 = ClientProfile(
    key="tibia-860-v2-custom-extended",
    client_version=860,
    label="Tibia 8.60 v2 customizado com features OTFI",
    dat_signature=0x4C2C7993,
    spr_signature=0x4C220594,
    metadata_reader=5,
    otb_version_hint="8.60",
)

TIBIA_1041 = ClientProfile(
    key="tibia-1041-custom",
    client_version=1041,
    label="Tibia 10.41 customizado",
    dat_signature=0x5383504E,
    spr_signature=0x53835077,
    metadata_reader=6,
    otb_version_hint="10.41",
)

PROFILES = (TIBIA_860_V2, TIBIA_1041)


def detect_profile(dat_signature: int, spr_signature: int) -> ClientProfile:
    for profile in PROFILES:
        if (
            profile.dat_signature == dat_signature
            and profile.spr_signature == spr_signature
        ):
            return profile
    raise ProfileError(
        "combinação DAT/SPR desconhecida: "
        f"DAT=0x{dat_signature:08X}, SPR=0x{spr_signature:08X}"
    )

