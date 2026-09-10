"""Organization business-verification (KYB) service.

KYB establishes an organization's legal identity once and every capability
reuses it. It used to live on the attestor application, which meant an org's
identity was verified only as a side effect of applying to be an Attestor while
Contributor and Operator capabilities self-activated unchecked.

The verdict attaches to ``OrgLegalProfile``, the row that already holds
``legal_name`` and ``registration_number`` and already feeds invoices, so an
identity and its verification cannot end up in different rows disagreeing about
who the organization legally is.

Review is manual: an org submits, an admin reads the documents and records a
verdict. Mirrors the individual KYC flow in ``admin.service.review_user_kyc``,
including that rejection is not terminal — the usual cause is an unreadable
document.

Maps to: DESIGN-1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.credential_service import (
    CREDENTIAL_EVIDENCE_MAX_BYTES,
    CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS,
    _safe_file_name,
)
from app.modules.organizations.models import Organization, OrgLegalProfile, OrgMember
from app.workers.tasks.project_notifications import dispatch_project_notification

# Incorporation uploads reuse the shared private-bucket evidence limits.
INCORPORATION_DOC_MAX_BYTES = CREDENTIAL_EVIDENCE_MAX_BYTES
INCORPORATION_DOC_UPLOAD_TTL_SECONDS = CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS
MAX_INCORPORATION_DOCS = 20

# Statuses whose identity fields the org may still edit. Once verified the
# legal name, registration number and documents are what an admin actually
# checked, so changing them has to send the profile back for review rather
# than silently keeping a badge earned under a different identity.
EDITABLE_KYB_STATUSES = ("unverified", "pending", "rejected")


@dataclass(frozen=True)
class IncorporationUploadTarget:
    """A presigned POST target for one incorporation document.

    Attributes:
        s3_key: Key the document will occupy, already attached to the profile.
        url: Presigned POST endpoint the browser submits to.
        fields: Form fields that must accompany the upload.
        expires_at: When the target stops being accepted.
    """

    s3_key: str
    url: str
    fields: dict[str, str]
    expires_at: datetime


async def org_kyb_verified(db: AsyncSession, *, org_id: UUID) -> bool:
    """Return whether an organization has passed business verification.

    Args:
        db: Async database session.
        org_id: Organization to check.

    Returns:
        True iff a legal profile exists and its KYB status is ``verified``.
    """
    status_value = await db.scalar(
        select(OrgLegalProfile.kyb_status).where(OrgLegalProfile.org_id == org_id)
    )
    return status_value == "verified"


async def require_org_kyb_verified(db: AsyncSession, *, org_id: UUID) -> None:
    """Raise unless the organization has passed business verification.

    Args:
        db: Async database session.
        org_id: Organization to check.

    Raises:
        HTTPException(403): The organization is not verified. The error names
            the surface that can clear the block, matching the incomplete-user
            contract the frontend already redirects on.
    """
    if await org_kyb_verified(db, org_id=org_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "org_kyb_required",
            "onboarding_url": f"/dashboard/organizations/{org_id}/verification",
        },
    )


async def _load_profile_locked(
    db: AsyncSession,
    org_id: UUID,
) -> OrgLegalProfile:
    """Return the org's legal profile for update, or raise 404."""
    profile = await db.scalar(
        select(OrgLegalProfile)
        .where(OrgLegalProfile.org_id == org_id)
        .with_for_update()
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submit the organization's legal details before its documents.",
        )
    return profile


async def add_incorporation_document(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    file_name: str,
    content_type: str,
    size_bytes: int,
) -> IncorporationUploadTarget:
    """Mint a presigned upload target for one incorporation document.

    The key is appended to the profile before the upload happens, so the list
    stays the single source of truth for which documents belong to this
    organization and a client cannot name its own key.

    Args:
        db: Async database session.
        org_id: Organization owning the profile.
        actor_id: Authenticated org owner/admin.
        file_name: Client-declared file name, sanitised into the key.
        content_type: Declared MIME type, bound into the presigned POST.
        size_bytes: Declared size, checked against the cap before signing.

    Returns:
        The upload target: object key, POST URL, form fields, and expiry.

    Raises:
        HTTPException(404): No legal profile exists yet.
        HTTPException(409): The profile is verified, or already holds the
            maximum number of documents.
        HTTPException(413): The declared upload exceeds the size limit.
    """
    if size_bytes > INCORPORATION_DOC_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Incorporation document upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    expires_at = datetime.now(UTC) + timedelta(
        seconds=INCORPORATION_DOC_UPLOAD_TTL_SECONDS
    )
    async with db.begin():
        profile = await _load_profile_locked(db, org_id)
        if profile.kyb_status not in EDITABLE_KYB_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Verified business details cannot be changed. Contact "
                    "support to update them."
                ),
            )
        if len(profile.incorporation_doc_keys) >= MAX_INCORPORATION_DOCS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Maximum number of incorporation documents already attached.",
            )
        key = (
            f"org-incorporation-docs/{org_id}/{profile.id}/"
            f"{uuid4()}-{_safe_file_name(file_name)}"
        )
        # Reassign rather than append so SQLAlchemy sees the ARRAY mutation.
        profile.incorporation_doc_keys = [*profile.incorporation_doc_keys, key]
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_incorporation_document_added",
            target_type="organization",
            target_id=org_id,
            metadata={"document_count": len(profile.incorporation_doc_keys)},
        )

    settings = get_settings()
    post = s3.storage.presigned_post(
        settings.s3_artifacts_bucket,
        key,
        content_type,
        INCORPORATION_DOC_MAX_BYTES,
        INCORPORATION_DOC_UPLOAD_TTL_SECONDS,
    )
    return IncorporationUploadTarget(
        s3_key=key,
        url=str(post["url"]),
        fields={str(name): str(value) for name, value in post["fields"].items()},
        expires_at=expires_at,
    )


async def remove_incorporation_document(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    s3_key: str,
) -> OrgLegalProfile:
    """Detach one incorporation document from the organization's profile.

    Args:
        db: Async database session.
        org_id: Organization owning the profile.
        actor_id: Authenticated org owner/admin.
        s3_key: Key to remove, which must already belong to this profile.

    Returns:
        The updated legal profile.

    Raises:
        HTTPException(404): No profile exists, or the key is not attached here.
        HTTPException(409): The profile is verified and therefore locked.
    """
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        profile = await _load_profile_locked(db, org_id)
        if profile.kyb_status not in EDITABLE_KYB_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Verified business details cannot be changed. Contact "
                    "support to update them."
                ),
            )
        if s3_key not in profile.incorporation_doc_keys:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incorporation document not found.",
            )
        profile.incorporation_doc_keys = [
            key for key in profile.incorporation_doc_keys if key != s3_key
        ]
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_incorporation_document_removed",
            target_type="organization",
            target_id=org_id,
            metadata={"document_count": len(profile.incorporation_doc_keys)},
        )
    await db.refresh(profile)
    return profile


async def submit_for_verification(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
) -> OrgLegalProfile:
    """Send the organization's business details for admin review.

    Args:
        db: Async database session.
        org_id: Organization submitting.
        actor_id: Authenticated org owner/admin.

    Returns:
        The profile, now ``pending``.

    Raises:
        HTTPException(404): No legal profile exists yet.
        HTTPException(409): Already verified, or already awaiting review.
        HTTPException(422): Registration number or documents are missing.
    """
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        profile = await _load_profile_locked(db, org_id)
        if profile.kyb_status == "verified":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This organization is already verified.",
            )
        if profile.kyb_status == "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="These details are already awaiting review.",
            )
        if not profile.registration_number:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A business registration number is required.",
            )
        if not profile.incorporation_doc_keys:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="At least one incorporation document is required.",
            )
        profile.kyb_status = "pending"
        profile.kyb_submitted_at = datetime.now(UTC)
        profile.kyb_review_notes = None
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_kyb_submitted",
            target_type="organization",
            target_id=org_id,
            metadata={"document_count": len(profile.incorporation_doc_keys)},
        )
    await db.refresh(profile)
    logger.bind(
        module="organizations",
        action="submit_org_kyb",
        user_id=str(actor_id),
        org_id=str(org_id),
    ).info("org_kyb_submitted")
    return profile


async def review_org_kyb(
    db: AsyncSession,
    *,
    org_id: UUID,
    admin_id: UUID,
    verdict: str,
    notes: str | None,
) -> OrgLegalProfile:
    """Record an admin's business-verification decision.

    Rejection is deliberately not terminal: the org may correct its details and
    submit again, since the usual cause is an unreadable or expired document.
    The caller performs admin TOTP step-up before this runs — verifying an
    organization unlocks every capability, so it is a sensitive write.

    Args:
        db: Async database session.
        org_id: Organization being decided.
        admin_id: Acting admin, stamped as reviewer and audited as actor.
        verdict: ``verified`` or ``rejected``.
        notes: Reason shown to the organization, required on rejection.

    Returns:
        The decided legal profile.

    Raises:
        HTTPException(404): No legal profile exists for the organization.
        HTTPException(409): The profile is not awaiting a decision.
        HTTPException(422): The verdict is unknown, or a rejection has no
            reason — an org told only "rejected" cannot act on it.
    """
    if verdict not in ("verified", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Verdict must be 'verified' or 'rejected'.",
        )
    if verdict == "rejected" and not (notes or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A rejection must say what the organization should fix.",
        )
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        organization = await db.get(Organization, org_id)
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found.",
            )
        profile = await _load_profile_locked(db, org_id)
        if profile.kyb_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This organization is not awaiting verification.",
            )
        if verdict == "verified":
            # A key is reserved when the upload target is minted, before the
            # browser sends anything, so a row can list documents that were
            # never uploaded. Verifying against those would certify an identity
            # nobody read.
            bucket = get_settings().s3_artifacts_bucket
            missing = [
                key
                for key in profile.incorporation_doc_keys
                if not s3.storage.object_exists(bucket, key)
            ]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "One or more incorporation documents were never "
                        "uploaded. Ask the organization to re-upload before "
                        "verifying."
                    ),
                )
        decided_at = datetime.now(UTC)
        profile.kyb_status = verdict
        profile.kyb_review_notes = (notes or "").strip() or None
        profile.kyb_verified_at = decided_at if verdict == "verified" else None
        profile.kyb_verified_by = admin_id if verdict == "verified" else None
        await write_audit(
            db=db,
            actor_id=admin_id,
            action=(
                "org_kyb_verified" if verdict == "verified" else "org_kyb_rejected"
            ),
            target_type="organization",
            target_id=org_id,
            metadata={"verdict": verdict, "has_notes": bool(notes)},
        )
    owner_ids = list(
        (
            await db.scalars(
                select(OrgMember.user_id).where(
                    OrgMember.org_id == org_id,
                    OrgMember.role == "owner",
                )
            )
        ).all()
    )
    await db.refresh(profile)
    # Dispatched after the commit so the worker reads the persisted verdict;
    # a queue failure is logged, never raised — mail must not undo a review.
    # The verification screen promises "we will let you know", so a verdict
    # that was only audited would break that promise.
    if verdict == "verified":
        title = "Your organization is verified"
        body = (
            f"{organization.name} passed business verification. You can now "
            "activate capabilities, invite members, and transact."
        )
    else:
        title = "Your organization's verification needs changes"
        body = (
            f"{organization.name} was not verified: "
            f"{profile.kyb_review_notes} Update the details and submit again."
        )
    for owner_id in owner_ids:
        try:
            dispatch_project_notification.delay(
                user_id=str(owner_id),
                notification_type=f"org_kyb_{verdict}",
                title=title,
                body=body,
                payload={"org_id": str(org_id)},
                link=f"/dashboard/organizations/{org_id}/verification",
                dedupe_key=(
                    f"org_kyb_{verdict}:{org_id}:{owner_id}:"
                    f"{decided_at.isoformat()}"
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive queue guard
            logger.bind(
                module="organizations",
                action="review_org_kyb",
                org_id=str(org_id),
            ).error("notification_dispatch_failed", error=str(exc))
    logger.bind(
        module="organizations",
        action="review_org_kyb",
        user_id=str(admin_id),
        org_id=str(org_id),
    ).info(f"org_kyb_{verdict}")
    return profile
