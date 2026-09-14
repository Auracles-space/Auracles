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
from app.modules.organizations import kyb_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
from app.shared.errors import error_detail

_ROLE_RANK = {"member": 0, "admin": 1, "owner": 2}
# One sentence per denial code, shown verbatim by the frontend.
_DENIAL_MESSAGES = {
    "org_role_required": "You do not have the required role in this organization.",
    "org_suspended": "This organization is suspended.",
    "capability_grant_required": (
        "You have not been granted this capability in the organization."
    ),
}
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
    error_code: str = "org_role_required",
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
        detail=error_detail(error_code, _DENIAL_MESSAGES[error_code]),
    )


def require_org_role(
    minimum_role: str,
    *,
    verified: bool = False,
) -> Callable[..., object]:
    """Build a dependency enforcing the caller's minimum organization role.

    Args:
        minimum_role: Lowest allowed role: ``member``, ``admin``, or ``owner``.
        verified: Also require the organization to have passed business
            verification. An unverified organization is a shell — it cannot
            invite, staff, sell, or transact — so almost every route sets this.
            The exceptions are the routes that lead *out* of the shell:
            verification itself, the legal profile it verifies, the org's own
            profile, and reads.
    """
    user_dependency = get_current_user

    # Depends lives in the default, not the annotation: postponed annotations
    # stringify `user_dependency`, which resolves against module globals and
    # would silently degrade the parameter to a required query field.
    async def checker(
        org_id: UUID,
        db: DatabaseSession,
        user: User = Depends(user_dependency),  # noqa: B008
    ) -> OrgContext:
        """Return organization context when the caller holds the required role."""
        organization, membership = await _load_org_context(db, org_id, user)
        if membership is None:
            await _deny(db, user, org_id, {"required_role": minimum_role})
        assert membership is not None

        if organization.suspended_at is not None:
            await _deny(
                db,
                user,
                org_id,
                {"reason": "org_suspended"},
                error_code="org_suspended",
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

        if verified:
            await kyb_service.require_org_kyb_verified(db, org_id=org_id)

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
                detail=error_detail(
                    "capability_required",
                    f"The organization's {capability} capability is not active.",
                    capability=capability,
                ),
            )

    return checker


def require_org_capability_grant(capability: str) -> Callable[..., object]:
    """Build a dependency enforcing a caller's team-scoped capability grant.

    A caller holds a grant only when the organization capability is active and
    the caller is an owner/admin or belongs to a team with the matching
    capability enabled.

    Args:
        capability: Capability slug required by the organization action.

    Returns:
        A dependency returning :class:`OrgContext` when the caller holds the
        active capability grant.
    """

    async def checker(
        org_id: UUID,
        db: DatabaseSession,
        user: Annotated[User, Depends(get_current_user)],
    ) -> OrgContext:
        """Return organization context when the caller holds the grant."""
        organization, membership = await _load_org_context(db, org_id, user)
        if membership is None:
            await _deny(db, user, org_id, {"required_capability": capability})
        assert membership is not None

        if organization.suspended_at is not None:
            await _deny(
                db,
                user,
                org_id,
                {"reason": "org_suspended"},
                error_code="org_suspended",
            )

        active = await db.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == capability,
                OrgCapability.status == "active",
            )
        )
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_detail(
                    "capability_required",
                    f"The organization's {capability} capability is not active.",
                    capability=capability,
                ),
            )

        if membership.role in {"owner", "admin"}:
            return OrgContext(org=organization, member=membership, user=user)

        team_grant = await db.scalar(
            select(OrgTeamMember.member_id)
            .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
            .join(
                OrgTeamCapability,
                (OrgTeamCapability.team_id == OrgTeam.id)
                & (OrgTeamCapability.capability == capability),
            )
            .where(
                OrgTeamMember.member_id == membership.id,
                OrgTeam.org_id == org_id,
            )
            .limit(1)
        )
        if team_grant is not None:
            return OrgContext(org=organization, member=membership, user=user)

        await _deny(
            db,
            user,
            org_id,
            {"required_capability": capability, "member_role": membership.role},
            error_code="capability_grant_required",
        )
        raise AssertionError("unreachable")

    return checker
