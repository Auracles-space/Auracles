"""Shared token schemas.

JWT payloads are decoded into Pydantic models so downstream dependencies can
consume typed identity data instead of raw dictionaries.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TokenPayload(BaseModel):
    """Decoded access token claims used by auth dependencies."""

    model_config = ConfigDict(extra="forbid")

    sub: UUID
    roles: list[str]
    exp: int
    iat: int
    jti: str
    totp_verified: bool = False
