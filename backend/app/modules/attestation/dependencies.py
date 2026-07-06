"""FastAPI dependencies for Attestation-specific access rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User
from app.modules.organizations.models import OrgMember

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]

_ATTESTOR_ORG_MANAGER_ROLES = ("owner", "admin")


@dataclass(frozen=True)
class AttestorActor:
    """Resolved attestor-side authority over one attestation.

    Attributes:
        is_reviewing_member: True when the caller performs the review — the
            reviewing member staffed on the org attestation. Grants write access
            to the review surfaces.
        is_org_manager: True when the caller is an owner/admin of the attestor
            organization. Grants read-only oversight.
        member_id: The reviewing OrgMember id, or None when the attestation has
            no reviewing member staffed yet.
    """

    is_reviewing_member: bool
    is_org_manager: bool
    member_id: UUID | None


async def attestor_actor(
    db: AsyncSession, *, attestation: Attestation, user_id: UUID
) -> AttestorActor:
    """Resolve the caller's attestor-side authority without raising.

    Returns an actor with both flags ``False`` when the caller has no attestor
    relationship to the attestation. Callers that need to reject unauthorized
    access should use :func:`resolve_attestor_actor` instead.

    Takes the caller's id (not the ORM ``User``) so it stays correct after a
    transaction rollback has expired the caller's instance.
    """
    org_id = attestation.attestor_org_id
    if org_id is None:
        return AttestorActor(
            is_reviewing_member=False, is_org_manager=False, member_id=None
        )

    membership = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user_id,
        )
    )
    if membership is None:
        return AttestorActor(
            is_reviewing_member=False, is_org_manager=False, member_id=None
        )
    if (
        attestation.reviewing_member_id is not None
        and membership.id == attestation.reviewing_member_id
    ):
        return AttestorActor(
            is_reviewing_member=True, is_org_manager=False, member_id=membership.id
        )
    if membership.role in _ATTESTOR_ORG_MANAGER_ROLES:
        return AttestorActor(
            is_reviewing_member=False, is_org_manager=True, member_id=None
        )
    return AttestorActor(
        is_reviewing_member=False, is_org_manager=False, member_id=None
    )


async def resolve_attestor_actor(
    db: AsyncSession,
    *,
    attestation: Attestation,
    user_id: UUID,
    allow_managers: bool = False,
) -> AttestorActor:
    """Authorize an attestor-side actor over an attestation or raise.

    The reviewing member may act on write surfaces. Org owners/admins are
    admitted read-only when ``allow_managers`` is set. A member of the attestor
    organization who is
    neither the reviewing member nor an admitted manager is refused (403); any
    other caller is hidden the attestation's existence (404).

    Args:
        db: Async database session.
        attestation: The attestation being acted on.
        user_id: The authenticated caller's id (rollback-safe).
        allow_managers: Whether org owners/admins are admitted (read surfaces).

    Returns:
        The resolved :class:`AttestorActor`.

    Raises:
        HTTPException(403): In the attestor org but not authorized for the
            surface.
        HTTPException(404): No relationship to the attestation.
    """
    actor = await attestor_actor(db, attestation=attestation, user_id=user_id)
    if actor.is_reviewing_member or (allow_managers and actor.is_org_manager):
        return actor
    if actor.is_org_manager or await _in_attestor_org(
        db, attestation=attestation, user_id=user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted for this attestation.",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Attestation not found.",
    )


async def _in_attestor_org(
    db: AsyncSession, *, attestation: Attestation, user_id: UUID
) -> bool:
    """Return whether the caller holds any membership in the attestor org."""
    if attestation.attestor_org_id is None:
        return False
    membership_id = await db.scalar(
        select(OrgMember.id).where(
            OrgMember.org_id == attestation.attestor_org_id,
            OrgMember.user_id == user_id,
        )
    )
    return membership_id is not None


async def require_approved_attestor(
    db: DatabaseSession,
    user: Annotated[User, Depends(require_role("attestor"))],
) -> User:
    """Require an authenticated Attestor.

    The ``attestor`` role is a derived role granted only to members of an
    organization whose ``attestor`` capability is active, so requiring the role
    is sufficient proof of an approved attestor relationship. Per-attestation
    authority is resolved separately via :func:`resolve_attestor_actor`.
    """
    del db
    return user
