"""Project operator-resolution helpers.

This module centralizes the additive user-or-organization operator branch used
by org-operated Project features without changing existing individual flows. It
mirrors the seller-resolution pattern used for org-owned Frameworks so every
project read path that asks "who operates this Project" resolves the same
descriptor regardless of ownership branch.

Maps to: Task 6 in docs/superpowers/specs/2026-07-10-org-operator-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.projects.models import Project


@dataclass(frozen=True)
class ProjectOperator:
    """Resolved operator identity for one Project.

    Attributes:
        kind: ``"user"`` for an individually-operated Project, ``"org"`` for an
            organization-operated Project.
        user_id: The operating User's id when ``kind == "user"``, else ``None``.
        org_id: The operating Organization's id when ``kind == "org"``, else
            ``None``.
    """

    kind: Literal["user", "org"]
    user_id: UUID | None
    org_id: UUID | None


def resolve_project_operator(project: Project) -> ProjectOperator:
    """Return the effective operator branch for one Project row.

    Args:
        project: The Project whose operator identity to resolve.

    Returns:
        A :class:`ProjectOperator` describing the individual or organization
        operator for the Project.
    """
    if project.operator_org_id is not None:
        return ProjectOperator(
            kind="org",
            user_id=None,
            org_id=project.operator_org_id,
        )
    return ProjectOperator(kind="user", user_id=project.operator_id, org_id=None)
