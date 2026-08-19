import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class TrackIdentity:
    identity_type: str
    identity_value: str
    track_key: str


def _normalize(value: object, *, uppercase: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    return normalized.upper() if uppercase else normalized


def resolve_track_identity(observation: dict[str, object]) -> TrackIdentity | None:
    candidates = (
        ("basic_id", _normalize(observation.get("basic_id"), uppercase=True)),
        ("session_id", _normalize(observation.get("session_id"))),
        ("mac", _normalize(observation.get("drone_mac"), uppercase=True)),
        ("operator_id", _normalize(observation.get("operator_id"), uppercase=True)),
    )

    for identity_type, identity_value in candidates:
        if identity_value is None:
            continue
        digest = hashlib.sha256(
            f"{identity_type}:{identity_value}".encode()
        ).hexdigest()[:24]
        return TrackIdentity(
            identity_type=identity_type,
            identity_value=identity_value,
            track_key=f"{identity_type}:{digest}",
        )

    return None
