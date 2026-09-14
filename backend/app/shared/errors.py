"""Structured HTTP error details.

Machine-readable denials carry a stable ``error_code`` the frontend can branch
on and a ``message`` it can show verbatim, so no route answers a bare code the
UI then has to translate.
"""

from __future__ import annotations


def error_detail(code: str, message: str, **extra: object) -> dict[str, object]:
    """Build an ``HTTPException`` detail carrying a code and a human sentence.

    Args:
        code: Stable snake_case error code, e.g. ``org_suspended``.
        message: One user-facing sentence explaining the refusal.
        **extra: Additional context fields (``capability``, ``onboarding_url``).

    Returns:
        A dict shaped ``{"error_code": code, "message": message, **extra}``.
    """
    return {"error_code": code, "message": message, **extra}
