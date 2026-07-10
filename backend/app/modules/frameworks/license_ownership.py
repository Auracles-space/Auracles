"""License holder-resolution helpers.

This module centralizes the additive user-or-organization holder branch used by
org-backed Operator features without changing existing individual flows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.frameworks.models import License


@dataclass(frozen=True)
class LicenseHolder:
    """Resolved holder identity for one License."""

    kind: Literal["user", "org"]
    user_id: UUID | None
    org_id: UUID | None


def resolve_license_holder(license_row: License) -> LicenseHolder:
    """Return the effective holder branch for one License row."""
    if license_row.licensee_org_id is not None:
        return LicenseHolder(
            kind="org",
            user_id=None,
            org_id=license_row.licensee_org_id,
        )
    return LicenseHolder(kind="user", user_id=license_row.operator_id, org_id=None)
