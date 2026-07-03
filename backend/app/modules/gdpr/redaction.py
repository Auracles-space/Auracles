"""Shared GDPR redaction helpers.

Provides recursive metadata redaction rules reused by GDPR export generation
and account anonymisation so both paths strip the same key-based and value-based
PII patterns.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
SENSITIVE_AUDIT_KEYS = {
    "email",
    "new_email",
    "ip",
    "ip_address",
    "provider_ref",
    "provider_account_id",
    "provider_account_lookup_hash",
    "raw_url",
    "url",
    "uploaded_filename",
    "filename",
    "note",
    "notes",
    "s3_key",
    "secret",
    "token",
    "bundle_key",
}


def _normalized_fragments(blocked_fragments: Iterable[str]) -> tuple[str, ...]:
    """Normalize free-text fragments that should trigger redaction."""
    return tuple(
        fragment.strip().lower() for fragment in blocked_fragments if fragment.strip()
    )


def contains_redacted_text(
    value: str,
    *,
    blocked_fragments: Iterable[str] = (),
) -> bool:
    """Return whether one string contains redaction-worthy PII patterns."""
    lowered = value.lower()
    if EMAIL_PATTERN.search(value) or URL_PATTERN.search(value):
        return True
    normalized_fragments = _normalized_fragments(blocked_fragments)
    return any(fragment in lowered for fragment in normalized_fragments)


def redact_metadata(
    value: Any,
    *,
    blocked_fragments: Iterable[str] = (),
) -> Any:
    """Recursively remove audit metadata values that may leak PII or secrets."""
    normalized_fragments = _normalized_fragments(blocked_fragments)
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_AUDIT_KEYS:
                continue
            scrubbed = redact_metadata(item, blocked_fragments=normalized_fragments)
            if scrubbed is not None:
                redacted[str(key)] = scrubbed
        return redacted
    if isinstance(value, list):
        return [
            scrubbed
            for item in value
            if (
                scrubbed := redact_metadata(
                    item,
                    blocked_fragments=normalized_fragments,
                )
            )
            is not None
        ]
    if isinstance(value, str):
        if contains_redacted_text(value, blocked_fragments=normalized_fragments):
            return None
    return value
