"""Public Attestor directory read models and query helpers.

Returns public-facing Attestor directory entries from active profiles only,
combining user display name, safe verified credential summaries, and a count
of completed Attestations.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation, AttestorProfile, Credential
from app.modules.attestation.schemas import (
    AttestorDirectoryEntry,
    PublicCredentialResponse,
)
from app.modules.auth.models import User
from app.modules.reputation import service as reputation_service

_COMPLETED_ATTESTATION_STATUSES = ("released", "resolved", "closed")


async def list_directory(
    db: AsyncSession,
    *,
    sector: str | None,
    framework_category: str | None,
    jurisdiction: str | None,
    level: int | None,
) -> list[AttestorDirectoryEntry]:
    """Return public directory entries for active Attestors matching filters."""
    query = (
        select(AttestorProfile, User.display_name)
        .join(User, User.id == AttestorProfile.user_id)
        .where(AttestorProfile.active.is_(True))
        .order_by(User.display_name, AttestorProfile.user_id)
    )
    if sector is not None:
        query = query.where(AttestorProfile.sectors.op("&&")([sector]))
    if framework_category is not None:
        query = query.where(
            AttestorProfile.framework_categories.op("&&")([framework_category])
        )
    if jurisdiction is not None:
        query = query.where(AttestorProfile.jurisdictions.op("&&")([jurisdiction]))
    if level is not None:
        query = query.where(AttestorProfile.verification_level == level)

    rows = (await db.execute(query)).all()
    return [
        await _directory_entry(
            db=db,
            user_id=profile.user_id,
            display_name=display_name,
            profile=profile,
        )
        for profile, display_name in rows
    ]


async def get_directory_profile(
    db: AsyncSession,
    user_id: UUID,
) -> AttestorDirectoryEntry:
    """Return one active Attestor directory entry or raise 404."""
    row = (
        await db.execute(
            select(AttestorProfile, User.display_name)
            .join(User, User.id == AttestorProfile.user_id)
            .where(
                AttestorProfile.user_id == user_id,
                AttestorProfile.active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Attestor not found.")

    profile, display_name = row
    return await _directory_entry(
        db=db,
        user_id=profile.user_id,
        display_name=display_name,
        profile=profile,
    )


async def _directory_entry(
    *,
    db: AsyncSession,
    user_id: UUID,
    display_name: str,
    profile: AttestorProfile,
) -> AttestorDirectoryEntry:
    """Build one public Attestor directory entry."""
    score = await reputation_service.get_score(
        db,
        subject_type="attestor",
        subject_id=user_id,
    )
    reputation = (
        float(score.score)
        if score is not None
        and score.is_provisional is False
        and score.score is not None
        else None
    )
    return AttestorDirectoryEntry(
        user_id=user_id,
        display_name=display_name,
        sectors=profile.sectors,
        framework_categories=profile.framework_categories,
        jurisdictions=profile.jurisdictions,
        verification_level=profile.verification_level,
        credentials=await _verified_credentials(db=db, user_id=user_id),
        completed_attestations=await _completed_attestations(db=db, user_id=user_id),
        reputation=reputation,
        certified=profile.certified_attestor_at is not None,
    )


async def _verified_credentials(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> list[PublicCredentialResponse]:
    """Return verified credentials safe for public display."""
    rows = await db.execute(
        select(Credential)
        .where(
            Credential.user_id == user_id,
            Credential.verification_status == "verified",
        )
        .order_by(Credential.issued_date.desc())
    )
    today = date.today()
    return [
        PublicCredentialResponse(
            title=credential.title,
            issuer=credential.issuer,
            credential_type=credential.credential_type,
            issued_date=credential.issued_date,
            expires_date=credential.expires_date,
            expired=(
                credential.expires_date is not None
                and credential.expires_date < today
            ),
        )
        for credential in rows.scalars().all()
    ]


async def _completed_attestations(*, db: AsyncSession, user_id: UUID) -> int:
    """Count completed Attestations issued by one Attestor."""
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Attestation)
            .where(
                Attestation.attestor_id == user_id,
                Attestation.status.in_(_COMPLETED_ATTESTATION_STATUSES),
            )
        )
        or 0
    )
