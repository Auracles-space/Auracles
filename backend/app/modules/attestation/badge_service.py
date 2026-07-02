"""Attestation badge & provenance service.

Writes the immutable badge snapshot when a framework-target Attestation closes
and becomes publication-eligible, and reads badges for the public and
owner/admin surfaces.

Maps to: Module 6c design spec sections 6 and 7.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation, AttestationBadge, Credential
from app.modules.attestation.schemas import AttestorCompletedAttestation
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework, FrameworkVersion

_PUBLIC_BADGE_OUTCOMES = ("approved", "conditional")


async def _public_credentials_snapshot(
    db: AsyncSession,
    *,
    attestor_id: UUID,
) -> list[dict[str, object]]:
    """Return verified credentials as public-safe JSON snapshot dictionaries."""
    rows = await db.execute(
        select(Credential)
        .where(
            Credential.user_id == attestor_id,
            Credential.verification_status == "verified",
        )
        .order_by(Credential.issued_date.desc())
    )
    today = date.today()
    return [
        {
            "title": credential.title,
            "issuer": credential.issuer,
            "credential_type": credential.credential_type,
            "issued_date": credential.issued_date.isoformat(),
            "expires_date": (
                credential.expires_date.isoformat()
                if credential.expires_date is not None
                else None
            ),
            "expired": (
                credential.expires_date is not None
                and credential.expires_date < today
            ),
        }
        for credential in rows.scalars().all()
    ]


async def publish_badge(db: AsyncSession, *, attestation: Attestation) -> None:
    """Write the immutable badge snapshot for a closed, eligible Attestation.

    Args:
        db: Async SQLAlchemy session.
        attestation: Closed Attestation being published.

    Returns:
        None. The snapshot is inserted as a side effect.
    """
    if attestation.target_type != "framework":
        return
    if not attestation.report_published_eligible:
        return
    if attestation.attestor_id is None or attestation.outcome is None:
        return

    version: str | None = None
    if attestation.framework_version_id is not None:
        resolved_version = await db.scalar(
            select(FrameworkVersion.version).where(
                FrameworkVersion.id == attestation.framework_version_id
            )
        )
        if isinstance(resolved_version, str):
            version = resolved_version

    display_name = await db.scalar(
        select(User.display_name).where(User.id == attestation.attestor_id)
    )
    credentials = await _public_credentials_snapshot(
        db,
        attestor_id=attestation.attestor_id,
    )

    await db.execute(
        pg_insert(AttestationBadge)
        .values(
            attestation_id=attestation.id,
            framework_id=attestation.target_id,
            review_type=attestation.review_type,
            outcome=attestation.outcome,
            attestor_id=attestation.attestor_id,
            attestor_display_name=(
                display_name if isinstance(display_name, str) else "Attestor"
            ),
            credentials_snapshot=credentials,
            framework_version=version,
            issued_at=attestation.closed_at or datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_attestation_badges_attestation")
    )
    logger.bind(
        module="attestation",
        action="publish_badge",
        attestation_id=attestation.id,
        framework_id=attestation.target_id,
    ).info("badge_published", outcome=attestation.outcome)


async def list_attestor_completed(
    db: AsyncSession,
    *,
    attestor_id: UUID,
) -> list[AttestorCompletedAttestation]:
    """Return an attestor's public positive completed attestations, newest first.

    Args:
        db: Async SQLAlchemy session.
        attestor_id: User id of the attestor.

    Returns:
        Positive completed-attestation entries with framework titles.
    """
    rows = (
        await db.execute(
            select(AttestationBadge, Framework.title)
            .join(Framework, Framework.id == AttestationBadge.framework_id)
            .where(
                AttestationBadge.attestor_id == attestor_id,
                AttestationBadge.outcome.in_(_PUBLIC_BADGE_OUTCOMES),
            )
            .order_by(AttestationBadge.issued_at.desc())
        )
    ).all()
    return [
        AttestorCompletedAttestation(
            framework_id=badge.framework_id,
            framework_title=title,
            review_type=badge.review_type,
            outcome=badge.outcome,
            issued_at=badge.issued_at,
            framework_version=badge.framework_version,
        )
        for badge, title in rows
    ]
