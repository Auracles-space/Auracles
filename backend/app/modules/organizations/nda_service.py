"""Org member NDA signing and assignability service.

Members of an organization that is pursuing the attestor capability (a
live attestor application) or already holds it (pending/active capability)
must sign the platform NDA (at its current config version) before they can
be staffed on Attestation work. One row per member; re-signing after a
version bump updates the row in place.

Maps to: docs/superpowers/specs/2026-07-04-org-attestor-design.md,
NDA-mechanics section.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.modules.organizations.models import (
    OrgAttestorApplication,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)

# Application statuses that count as "live" (pre-approval, still in flight).
# Kept in lockstep with attestor_application_service._LIVE_STATUSES; defined
# locally because that module imports this one (avoiding a circular import).
_LIVE_APPLICATION_STATUSES = ("draft", "submitted", "needs_info")


_NDA_DOCUMENT_DIR = Path(__file__).parent / "nda_documents"


class MissingNdaDocumentError(RuntimeError):
    """Raised when the configured NDA version has no document on disk."""


@lru_cache(maxsize=8)
def nda_document_text(version: str) -> str:
    """Return the agreement text for one NDA version.

    Versions are Markdown files named for the version string, so publishing new
    wording is adding a file and bumping ``ORG_MEMBER_NDA_VERSION`` — which is
    reviewable as a diff and keeps the text a signature refers to immutable.

    Args:
        version: NDA version string, e.g. ``"1.0"``.

    Returns:
        The document's Markdown source.

    Raises:
        MissingNdaDocumentError: No document exists for the version. Raised
            rather than returning empty text: a version bump that forgets its
            document would otherwise ask members to sign a blank agreement.
    """
    # The version reaches the filesystem, so refuse anything that is not a
    # plain version string rather than resolving a traversal into the package.
    if not version or not all(char.isalnum() or char in "._-" for char in version):
        raise MissingNdaDocumentError(f"Unsupported NDA version {version!r}.")
    document = _NDA_DOCUMENT_DIR / f"{version}.md"
    try:
        return document.read_text(encoding="utf-8")
    except OSError as exc:
        raise MissingNdaDocumentError(
            f"No NDA document for version {version!r}."
        ) from exc


@dataclass(frozen=True)
class NdaStatus:
    """A member's NDA position for one organization.

    Attributes:
        required: True iff the org's attestor capability is pending or active.
        current_version: Platform NDA version members must hold.
        document: Agreement text for ``current_version``, so every signing
            surface renders the same words rather than its own copy.
        signed_version: Version the member last signed, if any.
        signed_at: Timestamp of the member's last signature, if any.
    """

    required: bool
    current_version: str
    document: str
    signed_version: str | None
    signed_at: datetime | None


async def _get_member(db: AsyncSession, *, org_id: UUID, user_id: UUID) -> OrgMember:
    """Return the caller's membership row or raise 404."""
    member = await db.scalar(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user_id,
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization membership not found.",
        )
    return member


async def _nda_required(db: AsyncSession, *, org_id: UUID) -> bool:
    """True iff the org is pursuing or holds the attestor capability.

    The attestor capability row is only created at admin approval, but the
    trial-nomination gate runs mid-application and needs members to hold a
    current NDA signature. So the requirement also fires while a live
    (pre-approval) attestor application exists, not just once the capability
    is pending or active — otherwise members could never sign before approval.
    """
    capability = await db.scalar(
        select(OrgCapability).where(
            OrgCapability.org_id == org_id,
            OrgCapability.capability == "attestor",
            OrgCapability.status.in_(["pending", "active"]),
        )
    )
    if capability is not None:
        return True
    live_application = await db.scalar(
        select(OrgAttestorApplication).where(
            OrgAttestorApplication.org_id == org_id,
            OrgAttestorApplication.status.in_(_LIVE_APPLICATION_STATUSES),
        )
    )
    return live_application is not None


async def get_nda_status(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
) -> NdaStatus:
    """Return the caller's NDA status for one organization.

    Args:
        db: Async database session.
        org_id: Organization to check.
        user_id: Authenticated member's user id.

    Returns:
        NdaStatus with the requirement flag and any existing signature.

    Raises:
        HTTPException(404): Caller is not a member of the organization.
    """
    member = await _get_member(db, org_id=org_id, user_id=user_id)
    signature = await db.scalar(
        select(OrgMemberNda).where(OrgMemberNda.member_id == member.id)
    )
    version = get_settings().org_member_nda_version
    return NdaStatus(
        required=await _nda_required(db, org_id=org_id),
        current_version=version,
        document=nda_document_text(version),
        signed_version=signature.nda_version if signature else None,
        signed_at=signature.signed_at if signature else None,
    )


async def sign_nda(
    db: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
) -> OrgMemberNda:
    """Sign (or re-sign) the platform NDA at its current version.

    Upserts the member's single NDA row: a first signature inserts it,
    a re-sign after a version bump updates nda_version and signed_at.
    Commits and audits ``org_nda_signed``.

    Args:
        db: Async database session.
        org_id: Organization the membership belongs to.
        user_id: Authenticated member's user id.

    Returns:
        The persisted OrgMemberNda row.

    Raises:
        HTTPException(404): Caller is not a member of the organization.
    """
    member = await _get_member(db, org_id=org_id, user_id=user_id)
    version = get_settings().org_member_nda_version
    signature = await db.scalar(
        select(OrgMemberNda).where(OrgMemberNda.member_id == member.id)
    )
    if signature is None:
        signature = OrgMemberNda(
            member_id=member.id,
            nda_version=version,
            signed_at=datetime.now(UTC),
        )
        db.add(signature)
    else:
        signature.nda_version = version
        signature.signed_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=user_id,
        action="org_nda_signed",
        target_type="organization",
        target_id=org_id,
        metadata={"nda_version": version},
    )
    await db.commit()
    await db.refresh(signature)
    logger.bind(
        module="organizations",
        action="org_nda_signed",
        user_id=str(user_id),
    ).info("Org member NDA signed")
    return signature


async def member_is_assignable(db: AsyncSession, *, member_id: UUID) -> bool:
    """True iff the member holds a current-version NDA signature.

    Consumed by attestation staffing (accept-and-staff, trial nomination,
    reviewer reassignment) to gate member assignment.
    """
    signature = await db.scalar(
        select(OrgMemberNda).where(OrgMemberNda.member_id == member_id)
    )
    return (
        signature is not None
        and signature.nda_version == get_settings().org_member_nda_version
    )
