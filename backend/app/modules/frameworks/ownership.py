"""Framework seller-resolution helpers.

This module centralizes the additive user-or-organization seller branch used by
org-backed Contributor features without changing existing individual flows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.frameworks.models import Framework


@dataclass(frozen=True)
class FrameworkSeller:
    """Resolved seller identity for one Framework."""

    kind: Literal["user", "org"]
    user_id: UUID | None
    org_id: UUID | None


def resolve_framework_seller(framework: Framework) -> FrameworkSeller:
    """Return the effective seller branch for one Framework row."""
    if framework.contributor_org_id is not None:
        return FrameworkSeller(
            kind="org",
            user_id=None,
            org_id=framework.contributor_org_id,
        )
    return FrameworkSeller(kind="user", user_id=framework.contributor_id, org_id=None)
