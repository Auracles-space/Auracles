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
from app.modules.reputation import service as reputation_service

_COMPLETED_ATTESTATION_STATUSES = ("released", "resolved", "closed")


async def list_directory(
    db: AsyncSession,
    *,
    sector: str | None,
    function: str | None,
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
    if function is not None:
        query = query.where(
            OrgAttestorProfile.functions.op("&&")([function])
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
        functions=profile.functions,
        jurisdictions=profile.jurisdictions,
        verification_level=profile.verification_level,
        completed_attestations=await _completed_attestations(
            db=db, org_id=organization.id
        ),
        member_count=await _member_count(db=db, org_id=organization.id),
        reputation=await _org_reputation(db=db, org_id=organization.id),
        certified=profile.certified_attestor_at is not None,
    )


async def _org_reputation(*, db: AsyncSession, org_id: UUID) -> float | None:
    """Return the org's published reputation number, or None while provisional.

    Mirrors the public-surface visibility rule: a cold-start (provisional) or
    never-scored organization reads as None so the directory shows the "New"
    badge rather than an unearned number.
    """
    score = await reputation_service.get_score(
        db, subject_type="attestor_org", subject_id=org_id
    )
    if score is None or score.is_provisional or score.score is None:
        return None
    return float(score.score)


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
