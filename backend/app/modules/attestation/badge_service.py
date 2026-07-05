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

from app.modules.attestation.models import (
    Attestation,
    AttestationBadge,
    AttestorProfile,
    Credential,
)
from app.modules.attestation.schemas import (
    AttestorCompletedAttestation,
    PublicCredentialResponse,
)
from app.modules.auth.models import User
from app.modules.explore.schemas import AttestationBadgeDetail
from app.modules.frameworks.models import Framework, FrameworkVersion
from app.modules.organizations.models import Organization, OrgAttestorProfile

_PUBLIC_BADGE_OUTCOMES = ("approved", "conditional")


async def _public_credentials_snapshot(
    db: AsyncSession,
    *,
    attestor_id: UUID | None,
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
                credential.expires_date is not None and credential.expires_date < today
            ),
        }
        for credential in rows.scalars().all()
    ]


async def _badge_attestor_identity(
    db: AsyncSession,
    *,
    attestation: Attestation,
) -> dict[str, object]:
    """Resolve the badge identity snapshot for one publication-eligible Attestation.

    Org attestations snapshot the organization's name and slug plus its profile
    verification level; organizations carry no credential rows, so their snapshot
    lists none. Legacy individual attestations snapshot the assignee's display
    name, verified credentials, and profile verification level. Exactly one of
    ``attestor_id`` / ``attestor_org_id`` is populated (badge XOR CHECK).

    Args:
        db: Async SQLAlchemy session.
        attestation: Publication-eligible Attestation (org- or user-attested).

    Returns:
        Column values for the immutable badge snapshot.
    """
    if attestation.attestor_org_id is not None:
        org = await db.scalar(
            select(Organization).where(Organization.id == attestation.attestor_org_id)
        )
        level = await db.scalar(
            select(OrgAttestorProfile.verification_level).where(
                OrgAttestorProfile.org_id == attestation.attestor_org_id
            )
        )
        return {
            "attestor_id": None,
            "attestor_org_id": attestation.attestor_org_id,
            "attestor_org_slug": org.slug if org is not None else None,
            "verification_level": level,
            "display_name": org.name if org is not None else "Attestor",
            "credentials": [],
        }

    display_name = await db.scalar(
        select(User.display_name).where(User.id == attestation.attestor_id)
    )
    level = await db.scalar(
        select(AttestorProfile.verification_level).where(
            AttestorProfile.user_id == attestation.attestor_id
        )
    )
    credentials = await _public_credentials_snapshot(
        db,
        attestor_id=attestation.attestor_id,
    )
    return {
        "attestor_id": attestation.attestor_id,
        "attestor_org_id": None,
        "attestor_org_slug": None,
        "verification_level": level,
        "display_name": display_name if isinstance(display_name, str) else "Attestor",
        "credentials": credentials,
    }


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
    if attestation.outcome is None:
        return
    if attestation.attestor_org_id is None and attestation.attestor_id is None:
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

    identity = await _badge_attestor_identity(db, attestation=attestation)

    await db.execute(
        pg_insert(AttestationBadge)
        .values(
            attestation_id=attestation.id,
            framework_id=attestation.target_id,
            review_type=attestation.review_type,
            outcome=attestation.outcome,
            attestor_id=identity["attestor_id"],
            attestor_org_id=identity["attestor_org_id"],
            attestor_org_slug=identity["attestor_org_slug"],
            verification_level=identity["verification_level"],
            attestor_display_name=identity["display_name"],
            credentials_snapshot=identity["credentials"],
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
    org_id: UUID,
) -> list[AttestorCompletedAttestation]:
    """Return an attestor org's public positive completed attestations, newest first.

    Args:
        db: Async SQLAlchemy session.
        org_id: Id of the attestor organization.

    Returns:
        Positive completed-attestation entries with framework titles.
    """
    rows = (
        await db.execute(
            select(AttestationBadge, Framework.title)
            .join(Framework, Framework.id == AttestationBadge.framework_id)
            .where(
                AttestationBadge.attestor_org_id == org_id,
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


async def list_framework_provenance(
    db: AsyncSession,
    *,
    framework: Framework,
) -> list[AttestationBadgeDetail]:
    """Return all badges for a framework including rejected provenance rows.

    Args:
        db: Async SQLAlchemy session.
        framework: Framework whose full badge provenance should be rendered.

    Returns:
        All immutable badge snapshots for the framework, newest first.
    """
    rows = (
        await db.execute(
            select(AttestationBadge)
            .where(AttestationBadge.framework_id == framework.id)
            .order_by(AttestationBadge.issued_at.desc(), AttestationBadge.id.desc())
        )
    ).scalars()
    return [
        AttestationBadgeDetail(
            id=badge.id,
            review_type=badge.review_type,
            outcome=badge.outcome,
            attestor_id=badge.attestor_id,
            attestor_org_id=badge.attestor_org_id,
            attestor_org_slug=badge.attestor_org_slug,
            attestor_display_name=badge.attestor_display_name,
            verification_level=badge.verification_level,
            credentials=[
                PublicCredentialResponse.model_validate(cred)
                for cred in badge.credentials_snapshot
            ],
            issued_at=badge.issued_at,
            framework_version=badge.framework_version,
            newer_version_exists=(
                badge.framework_version is not None
                and badge.framework_version != framework.version
            ),
        )
        for badge in rows.all()
    ]
