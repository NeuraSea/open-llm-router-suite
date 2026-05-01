from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    name: str
    team_ids: list[str]
    role: str
    avatar_url: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
