"""Organization-scoped RBAC dependencies.

Layered after ``get_current_user``; role hierarchy is owner > admin >
member. RBAC decisions are made here and audited before raising.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.organizations.models import Organization, OrgCapability, OrgMember

_ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class OrgContext:
    """Resolved organization, membership row, and authenticated user."""

    org: Organization
    member: OrgMember
    user: User


async def _load_org_context(
    db: AsyncSession,
    org_id: UUID,
    user: User,
) -> tuple[Organization, OrgMember | None]:
    """Load an active organization and the caller's membership row."""
    organization = await db.scalar(
        select(Organization).where(
            Organization.id == org_id,
            Organization.deactivated_at.is_(None),
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )

    membership = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
        )
    )
    return organization, membership


async def _deny(
    db: AsyncSession,
    user: User,
    org_id: UUID,
    metadata: dict[str, object],
) -> None:
    """Audit an org-RBAC denial and raise 403."""
    await write_audit(
        db=db,
        actor_id=user.id,
        action="access_denied",
        target_type="org_rbac",
        target_id=org_id,
        metadata=metadata,
    )
    await db.commit()
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error_code": "org_role_required"},
    )


def require_org_role(minimum_role: str) -> Callable[..., object]:
    """Build a dependency enforcing the caller's minimum organization role.

    Args:
        minimum_role: Lowest allowed role: ``member``, ``admin``, or ``owner``.
    """

    async def checker(
        org_id: UUID,
        db: DatabaseSession,
        user: Annotated[User, Depends(get_current_user)],
    ) -> OrgContext:
        """Return organization context when the caller holds the required role."""
        organization, membership = await _load_org_context(db, org_id, user)
        if membership is None:
            await _deny(db, user, org_id, {"required_role": minimum_role})
        assert membership is not None

        if organization.suspended_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "org_suspended"},
            )

        if _ROLE_RANK[membership.role] < _ROLE_RANK[minimum_role]:
            await _deny(
                db,
                user,
                org_id,
                {
                    "required_role": minimum_role,
                    "member_role": membership.role,
                },
            )

        return OrgContext(org=organization, member=membership, user=user)

    return checker


def require_org_capability(capability: str) -> Callable[..., object]:
    """Build a dependency requiring one active organization capability."""

    async def checker(
        org_id: UUID,
        db: DatabaseSession,
        user: Annotated[User, Depends(get_current_user)],
    ) -> None:
        """Raise 403 unless the organization capability is active."""
        del user
        row = await db.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == capability,
                OrgCapability.status == "active",
            )
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "capability_required", "capability": capability},
            )

    return checker
