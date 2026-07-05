"""Public attestor-organization directory read models and query helpers.

Returns public-facing directory entries for active attestor organizations only,
combining the organization's public matching profile, a count of completed
Attestations credited to the organization, its member count, and its
certification mark. Individual member identities are never exposed — attestation
is an organizational activity, not an individual advertisement.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation
from app.modules.attestation.schemas import AttestorDirectoryEntry
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgMember,
)

_COMPLETED_ATTESTATION_STATUSES = ("released", "resolved", "closed")


async def list_directory(
    db: AsyncSession,
    *,
    sector: str | None,
    framework_category: str | None,
    jurisdiction: str | None,
    level: int | None,
) -> list[AttestorDirectoryEntry]:
    """Return public directory entries for active attestor orgs matching filters."""
    query = (
        select(OrgAttestorProfile, Organization)
        .join(Organization, Organization.id == OrgAttestorProfile.org_id)
        .where(
            OrgAttestorProfile.active.is_(True),
            Organization.suspended_at.is_(None),
            Organization.deactivated_at.is_(None),
        )
        .order_by(Organization.name, OrgAttestorProfile.org_id)
    )
    if sector is not None:
        query = query.where(OrgAttestorProfile.sectors.op("&&")([sector]))
    if framework_category is not None:
        query = query.where(
            OrgAttestorProfile.framework_categories.op("&&")([framework_category])
        )
    if jurisdiction is not None:
        query = query.where(OrgAttestorProfile.jurisdictions.op("&&")([jurisdiction]))
    if level is not None:
        query = query.where(OrgAttestorProfile.verification_level == level)

    rows = (await db.execute(query)).all()
    return [
        await _directory_entry(db=db, profile=profile, organization=organization)
        for profile, organization in rows
    ]


async def get_directory_profile(
    db: AsyncSession,
    org_id: UUID,
) -> AttestorDirectoryEntry:
    """Return one active attestor-org directory entry or raise 404."""
    row = (
        await db.execute(
            select(OrgAttestorProfile, Organization)
            .join(Organization, Organization.id == OrgAttestorProfile.org_id)
            .where(
                OrgAttestorProfile.org_id == org_id,
                OrgAttestorProfile.active.is_(True),
                Organization.suspended_at.is_(None),
                Organization.deactivated_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Attestor organization not found.")

    profile, organization = row
    return await _directory_entry(db=db, profile=profile, organization=organization)


async def _directory_entry(
    *,
    db: AsyncSession,
    profile: OrgAttestorProfile,
    organization: Organization,
) -> AttestorDirectoryEntry:
    """Build one public attestor-org directory entry."""
    return AttestorDirectoryEntry(
        org_id=organization.id,
        name=organization.name,
        slug=organization.slug,
        sectors=profile.sectors,
        framework_categories=profile.framework_categories,
        jurisdictions=profile.jurisdictions,
        verification_level=profile.verification_level,
        completed_attestations=await _completed_attestations(
            db=db, org_id=organization.id
        ),
        member_count=await _member_count(db=db, org_id=organization.id),
        # Org reputation scoring is wired in Task 10; None until then.
        reputation=None,
        certified=profile.certified_attestor_at is not None,
    )


async def _completed_attestations(*, db: AsyncSession, org_id: UUID) -> int:
    """Count completed Attestations credited to one attestor organization."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Attestation)
            .where(
                Attestation.attestor_org_id == org_id,
                Attestation.status.in_(_COMPLETED_ATTESTATION_STATUSES),
            )
        )
        or 0
    )


async def _member_count(*, db: AsyncSession, org_id: UUID) -> int:
    """Count members of one organization for the public directory entry."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(OrgMember)
            .where(OrgMember.org_id == org_id)
        )
        or 0
    )
