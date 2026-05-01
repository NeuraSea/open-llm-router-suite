from __future__ import annotations

from typing import Protocol


class SecretCodec(Protocol):
    def encode(self, plain: str | None) -> str | None:
        ...

    def decode(self, stored: str | None) -> str | None:
        ...


class PassthroughSecretCodec:
    def encode(self, plain: str | None) -> str | None:
        return plain

    def decode(self, stored: str | None) -> str | None:
        return stored
