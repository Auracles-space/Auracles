"""Pydantic schemas for the public waitlist endpoint.

Maps to FR marketing pre-launch capture: validated email in, idempotent
join status out.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class WaitlistJoinRequest(BaseModel):
    """Request body for joining the pre-launch waitlist."""

    email: EmailStr
    source: str | None = Field(
        default=None,
        max_length=50,
        description="Optional origin hint for the signup (e.g. 'hero', 'footer').",
    )


class WaitlistJoinResponse(BaseModel):
    """Result of a waitlist join attempt.

    `already_joined` is True when the email was previously recorded, letting the
    client confirm the spot without leaking whether the address is new.
    """

    already_joined: bool
    message: str
