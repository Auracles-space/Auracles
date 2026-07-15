"""Org attestor application (org-side) service.

Drives the organization half of the attestor activation flow: opening and
editing a draft application, submitting it for admin review, owner-signed
undertakings, the payout and tax-document gates, and nominating the member
who performs the calibration trial. A single ``org_attestor_applications``
row carries every per-gate stamp so the admin gate checklist reads directly
from it.

Maps to: docs/superpowers/specs/2026-07-04-org-attestor-design.md, the
"Org attestor application" API-surface block. RBAC is enforced by router
dependencies; this layer assumes an authorized org owner/admin actor.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.credential_service import (
    CREDENTIAL_EVIDENCE_MAX_BYTES,
    CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS,
    _safe_file_name,
)
from app.modules.attestation.models import AttestorTrial
from app.modules.attestation.schemas import CredentialEvidenceUploadSessionResponse
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials.models import PayoutAccount
from app.modules.organizations import nda_service
from app.modules.organizations.models import (
    OrgAttestorApplication,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
)
from app.modules.organizations.schemas import (
    OrgAttestorApplicationCreateRequest,
    OrgAttestorApplicationUpdateRequest,
    OrgAttestorDocumentLink,
    OrgAttestorGateChecklist,
    OrgAttestorIncorporationDocumentRequest,
    OrgAttestorTaxDocumentRequest,
    OrgUndertakingsSignRequest,
)
from app.workers.tasks.project_notifications import dispatch_project_notification

# Org tax-document uploads reuse the shared credential-evidence upload limits.
TAX_DOCUMENT_MAX_BYTES = CREDENTIAL_EVIDENCE_MAX_BYTES
TAX_DOCUMENT_UPLOAD_TTL_SECONDS = CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS

# Incorporation-document uploads reuse the same private-bucket upload limits and
# cap how many KYB documents one application may attach.
INCORPORATION_DOC_MAX_BYTES = CREDENTIAL_EVIDENCE_MAX_BYTES
INCORPORATION_DOC_UPLOAD_TTL_SECONDS = CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS
MAX_INCORPORATION_DOCS = 20

# Admin review download links follow the platform-wide 15-minute presigned-URL
# expiry so a shared or logged link goes stale quickly.
DOCUMENT_DOWNLOAD_TTL_SECONDS = 900

# S3 keys are minted as ``{uuid4}-{safe_file_name}``; the uuid4 string is a
# fixed 36 characters followed by a hyphen, so the original name is everything
# after that prefix.
_UUID_KEY_PREFIX_LEN = 37

# CoI/confidentiality validity window: the undertakings gate stamps
# coi_expires_at one year out.
COI_VALIDITY = timedelta(days=365)

# Statuses under the org's live-application uniqueness guarantee.
_LIVE_STATUSES = ("draft", "submitted", "needs_info")
# Statuses that still accept content edits.
_EDITABLE_STATUSES = ("draft", "needs_info")
# Statuses that still accept gate completion (undertakings, tax, nomination).
_GATEABLE_STATUSES = ("draft", "submitted", "needs_info")


async def _load_live_locked(
    db: AsyncSession,
    org_id: UUID,
    *,
    allowed_statuses: tuple[str, ...],
) -> OrgAttestorApplication:
    """Load and lock the org's live application, enforcing an allowed status.

    Args:
        db: Async session inside an open transaction.
        org_id: Organization whose live application is loaded.
        allowed_statuses: Statuses under which the requested operation is legal.

    Returns:
        The locked live application row.

    Raises:
        HTTPException(404): If the org has no live application.
        HTTPException(409): If the live application is not in an allowed status.
    """
    application = await db.scalar(
        select(OrgAttestorApplication)
        .where(
            OrgAttestorApplication.org_id == org_id,
            OrgAttestorApplication.status.in_(_LIVE_STATUSES),
        )
        .with_for_update()
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Org attestor application not found.",
        )
    if application.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application cannot be modified in status {application.status!r}.",
        )
    return application


async def _trial_passed(db: AsyncSession, application_id: UUID) -> bool:
    """True iff a passed calibration trial exists for the application."""
    trial = await db.scalar(
        select(AttestorTrial).where(
            AttestorTrial.org_application_id == application_id,
            AttestorTrial.status == "passed",
        )
    )
    return trial is not None


async def _gate_checklist(
    db: AsyncSession,
    application: OrgAttestorApplication,
) -> OrgAttestorGateChecklist:
    """Derive the per-gate readiness flags for one application row."""
    return OrgAttestorGateChecklist(
        kyb_verified=application.kyb_verified_at is not None,
        # Credentials count as reviewed once an admin has reviewed the
        # application and advanced it past the needs-info state.
        credentials_reviewed=(
            application.reviewed_at is not None
            and application.status not in ("draft", "needs_info")
        ),
        undertakings_signed=(
            application.coi_signed_at is not None
            and application.confidentiality_signed_at is not None
        ),
        payout_account_linked=application.payout_account_id is not None,
        tax_document_uploaded=application.tax_document_key is not None,
        trial_passed=await _trial_passed(db, application.id),
    )


async def create_application(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    payload: OrgAttestorApplicationCreateRequest,
) -> OrgAttestorApplication:
    """Open (or reapply for) an org attestor application as a draft.

    Args:
        db: Async session.
        org_id: Organization opening the application.
        actor_id: Authenticated org owner/admin acting.
        payload: Matching and credentials content, plus optional KYB fields.

    Returns:
        The newly created draft application.

    Raises:
        HTTPException(409): If the org already holds an active attestor
            capability, or a live application already exists.
    """
    if db.in_transaction():
        await db.rollback()

    # The partial unique index (uq_org_attestor_app_live) is the race-safe
    # backstop for two concurrent creates that both pass the checks below.
    try:
        async with db.begin():
            active_capability = await db.scalar(
                select(OrgCapability).where(
                    OrgCapability.org_id == org_id,
                    OrgCapability.capability == "attestor",
                    OrgCapability.status == "active",
                )
            )
            if active_capability is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Organization is already an active attestor.",
                )
            application = OrgAttestorApplication(
                org_id=org_id,
                status="draft",
                # Legacy NOT NULL column superseded by sectors/functions.
                specializations=[],
                legal_name=payload.legal_name,
                registration_number=payload.registration_number,
                # Incorporation docs are attached after creation via the
                # dedicated upload endpoint; the column defaults to empty.
                sectors=payload.sectors,
                functions=payload.functions,
                jurisdictions=payload.jurisdictions,
                credentials_summary=payload.credentials_summary,
                sample_work=payload.sample_work,
                professional_references=payload.professional_references,
            )
            db.add(application)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=actor_id,
                action="org_attestor_application_created",
                target_type="org_attestor_application",
                target_id=application.id,
                metadata={"org_id": str(org_id)},
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A live attestor application already exists for this organization.",
        ) from exc

    logger.bind(
        module="organizations",
        action="org_attestor_application_created",
        user_id=str(actor_id),
    ).info("Org attestor application created")
    return application


async def get_application(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> tuple[OrgAttestorApplication, OrgAttestorGateChecklist]:
    """Return the org's most recent attestor application and its gate checklist.

    Args:
        db: Async session.
        org_id: Organization whose application is read.

    Returns:
        A tuple of the application row and its derived gate checklist.

    Raises:
        HTTPException(404): If the org has no attestor application.
    """
    application = await db.scalar(
        select(OrgAttestorApplication)
        .where(OrgAttestorApplication.org_id == org_id)
        .order_by(OrgAttestorApplication.created_at.desc())
        .limit(1)
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Org attestor application not found.",
        )
    checklist = await _gate_checklist(db, application)
    return application, checklist


async def get_application_by_id(
    db: AsyncSession,
    *,
    application_id: UUID,
) -> tuple[OrgAttestorApplication, OrgAttestorGateChecklist]:
    """Return one application (by id) and its gate checklist, for admin reads.

    Raises:
        HTTPException(404): If the application does not exist.
    """
    application = await db.scalar(
        select(OrgAttestorApplication).where(
            OrgAttestorApplication.id == application_id
        )
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Org attestor application not found.",
        )
    checklist = await _gate_checklist(db, application)
    return application, checklist


async def update_application(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    payload: OrgAttestorApplicationUpdateRequest,
) -> OrgAttestorApplication:
    """Partially edit a draft or needs-info application in place.

    Only the fields present in ``payload`` are applied. Supplying
    ``payout_account_id`` links an org-owned payout account to the payout gate.

    Args:
        db: Async session.
        org_id: Organization owning the application.
        actor_id: Authenticated org owner/admin acting.
        payload: Partial field updates.

    Returns:
        The updated application.

    Raises:
        HTTPException(404): If no live application or payout account is found.
        HTTPException(409): If the application is not in draft/needs_info.
    """
    if db.in_transaction():
        await db.rollback()
    fields = payload.model_dump(exclude_unset=True)
    async with db.begin():
        application = await _load_live_locked(
            db, org_id, allowed_statuses=_EDITABLE_STATUSES
        )
        payout_account_id = fields.pop("payout_account_id", None)
        if payout_account_id is not None:
            account = await db.scalar(
                select(PayoutAccount).where(
                    PayoutAccount.id == payout_account_id,
                    PayoutAccount.org_id == org_id,
                    PayoutAccount.deleted_at.is_(None),
                )
            )
            if account is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Payout account not found for this organization.",
                )
            application.payout_account_id = payout_account_id
        for key, value in fields.items():
            setattr(application, key, value)
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_attestor_application_updated",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"fields": sorted(payload.model_dump(exclude_unset=True))},
        )
    return application


def _kyb_complete(application: OrgAttestorApplication) -> bool:
    """True iff every KYB, matching, and credentials field is populated."""
    return bool(
        application.legal_name
        and application.registration_number
        and application.incorporation_doc_keys
        and application.sectors
        and application.functions
        and application.jurisdictions
        and application.credentials_summary
        and application.professional_references
    )


async def submit_application(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
) -> OrgAttestorApplication:
    """Submit a completed draft/needs-info application for admin review.

    Args:
        db: Async session.
        org_id: Organization owning the application.
        actor_id: Authenticated org owner/admin acting.

    Returns:
        The application transitioned to ``submitted``.

    Raises:
        HTTPException(404): If no live application exists.
        HTTPException(409): If the application is not in draft/needs_info.
        HTTPException(422): If KYB/matching/credentials fields are incomplete.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await _load_live_locked(
            db, org_id, allowed_statuses=_EDITABLE_STATUSES
        )
        if not _kyb_complete(application):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Complete all KYB, matching, and credentials fields "
                    "before submitting."
                ),
            )
        application.status = "submitted"
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_attestor_application_submitted",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"org_id": str(org_id)},
        )
    logger.bind(
        module="organizations",
        action="org_attestor_application_submitted",
        user_id=str(actor_id),
    ).info("Org attestor application submitted")
    return application


async def sign_undertakings(
    db: AsyncSession,
    redis: Redis,
    *,
    org_id: UUID,
    user: User,
    payload: OrgUndertakingsSignRequest,
) -> OrgAttestorApplication:
    """Owner-sign the CoI and confidentiality undertakings (TOTP-gated).

    Stamps ``coi_signed_at`` and ``confidentiality_signed_at`` to now and
    ``coi_expires_at`` one validity period out, and records the declared
    conflicts of interest.

    Args:
        db: Async session.
        redis: Redis client for TOTP lockout accounting.
        org_id: Organization owning the application.
        user: Authenticated org owner performing the sensitive action.
        payload: Declarations, acceptance flags, and TOTP code.

    Returns:
        The application with undertakings stamped.

    Raises:
        HTTPException(404): If no live application exists.
        HTTPException(403/422): If TOTP is absent or invalid.
        HTTPException(422): If either undertaking is not accepted.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await _load_live_locked(
            db, org_id, allowed_statuses=_GATEABLE_STATUSES
        )
        if not payload.accept_policy or not payload.accept_confidentiality:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Both undertakings must be accepted.",
            )
        # Reload the user inside the transaction: the rollback above expired
        # the dependency-loaded instance, so its TOTP attributes must be
        # re-fetched before the sensitive-action check reads them.
        locked_user = await db.get(User, user_id, with_for_update=True)
        if locked_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_user,
            code=payload.totp_code,
        )
        now = datetime.now(UTC)
        application.coi_declarations = [
            declaration.model_dump(mode="json") for declaration in payload.declarations
        ]
        application.coi_signed_at = now
        application.coi_expires_at = now + COI_VALIDITY
        application.confidentiality_signed_at = now
        await write_audit(
            db=db,
            actor_id=user_id,
            action="org_attestor_undertakings_signed",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"declaration_count": len(payload.declarations)},
        )
    logger.bind(
        module="organizations",
        action="org_attestor_undertakings_signed",
        user_id=str(user_id),
    ).info("Org attestor undertakings signed")
    return application


async def set_tax_document(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    payload: OrgAttestorTaxDocumentRequest,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned upload session for the org's tax document.

    Stamps the application's declared tax document type and S3 key, then
    returns a presigned POST for the org to upload the document directly.

    Args:
        db: Async session.
        org_id: Organization owning the application.
        actor_id: Authenticated org owner/admin acting.
        payload: Declared tax-document type and upload metadata.

    Returns:
        A presigned POST upload session response for the tax document.

    Raises:
        HTTPException(404): If no live application exists.
        HTTPException(409): If the application is not gate-eligible.
        HTTPException(413): If the upload exceeds the size limit.
    """
    if payload.size_bytes > TAX_DOCUMENT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Tax document upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=TAX_DOCUMENT_UPLOAD_TTL_SECONDS)
    async with db.begin():
        application = await _load_live_locked(
            db, org_id, allowed_statuses=_GATEABLE_STATUSES
        )
        key = (
            f"org-attestor-tax-documents/{org_id}/{application.id}/"
            f"{uuid4()}-{_safe_file_name(payload.file_name)}"
        )
        application.tax_document_type = payload.tax_document_type
        application.tax_document_key = key
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_attestor_tax_document_set",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"tax_document_set": True},
        )

    settings = get_settings()
    post = s3.storage.presigned_post(
        settings.s3_artifacts_bucket,
        key,
        payload.content_type,
        TAX_DOCUMENT_MAX_BYTES,
        TAX_DOCUMENT_UPLOAD_TTL_SECONDS,
    )
    return CredentialEvidenceUploadSessionResponse(
        id=uuid4(),
        s3_key=key,
        url=str(post["url"]),
        fields={str(k): str(v) for k, v in post["fields"].items()},
        expires_at=expires_at,
        size_limit=TAX_DOCUMENT_MAX_BYTES,
        scan_status="pending_scan",
    )


async def add_incorporation_document(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    payload: OrgAttestorIncorporationDocumentRequest,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned upload session for one incorporation document.

    Appends a freshly minted S3 key to the application's
    ``incorporation_doc_keys`` list, then returns a presigned POST so the org
    can upload the document directly to the private bucket. The list is the
    single source of truth for KYB documents, so keys are never supplied by the
    create/update payload.

    Args:
        db: Async session.
        org_id: Organization owning the application.
        actor_id: Authenticated org owner/admin acting.
        payload: Upload metadata (file name, content type, declared size).

    Returns:
        A presigned POST upload session response for the incorporation document.

    Raises:
        HTTPException(404): If no live application exists.
        HTTPException(409): If the application is not gate-eligible, or already
            holds the maximum number of incorporation documents.
        HTTPException(413): If the upload exceeds the size limit.
    """
    if payload.size_bytes > INCORPORATION_DOC_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Incorporation document upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=INCORPORATION_DOC_UPLOAD_TTL_SECONDS)
    async with db.begin():
        application = await _load_live_locked(
            db, org_id, allowed_statuses=_GATEABLE_STATUSES
        )
        if len(application.incorporation_doc_keys) >= MAX_INCORPORATION_DOCS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Maximum number of incorporation documents already attached."
                ),
            )
        key = (
            f"org-attestor-incorporation-docs/{org_id}/{application.id}/"
            f"{uuid4()}-{_safe_file_name(payload.file_name)}"
        )
        # Reassign (not append) so SQLAlchemy detects the mutation on the
        # ARRAY column and flushes the new key.
        application.incorporation_doc_keys = [
            *application.incorporation_doc_keys,
            key,
        ]
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_attestor_incorporation_document_added",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"incorporation_doc_added": True},
        )

    settings = get_settings()
    post = s3.storage.presigned_post(
        settings.s3_artifacts_bucket,
        key,
        payload.content_type,
        INCORPORATION_DOC_MAX_BYTES,
        INCORPORATION_DOC_UPLOAD_TTL_SECONDS,
    )
    return CredentialEvidenceUploadSessionResponse(
        id=uuid4(),
        s3_key=key,
        url=str(post["url"]),
        fields={str(k): str(v) for k, v in post["fields"].items()},
        expires_at=expires_at,
        size_limit=INCORPORATION_DOC_MAX_BYTES,
        scan_status="pending_scan",
    )


async def remove_incorporation_document(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    s3_key: str,
) -> OrgAttestorApplication:
    """Remove one incorporation document key from the application.

    Args:
        db: Async session.
        org_id: Organization owning the application.
        actor_id: Authenticated org owner/admin acting.
        s3_key: The incorporation-document key to detach.

    Returns:
        The application with the key removed.

    Raises:
        HTTPException(404): If no live application exists, or the key is not
            attached to the application.
        HTTPException(409): If the application is not gate-eligible.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await _load_live_locked(
            db, org_id, allowed_statuses=_GATEABLE_STATUSES
        )
        if s3_key not in application.incorporation_doc_keys:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incorporation document not found.",
            )
        application.incorporation_doc_keys = [
            key for key in application.incorporation_doc_keys if key != s3_key
        ]
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_attestor_incorporation_document_removed",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"incorporation_doc_removed": True},
        )
    return application


async def nominate_trial_member(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    member_id: UUID,
) -> OrgAttestorApplication:
    """Nominate the org member who will perform the calibration trial.

    Args:
        db: Async session.
        org_id: Organization owning the application.
        actor_id: Authenticated org owner/admin acting.
        member_id: Org member nominated to perform the trial review.

    Returns:
        The application with the nominated trial member stamped.

    Raises:
        HTTPException(404): If no live application, or the member is not in
            the organization.
        HTTPException(422): If the member has not signed the current NDA.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await _load_live_locked(
            db, org_id, allowed_statuses=_GATEABLE_STATUSES
        )
        member = await db.scalar(
            select(OrgMember).where(
                OrgMember.id == member_id,
                OrgMember.org_id == org_id,
            )
        )
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Org member not found.",
            )
        if not await nda_service.member_is_assignable(db, member_id=member_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error_code": "nda_required"},
            )
        application.trial_member_id = member_id
        nominee_user_id = member.user_id
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_attestor_trial_member_nominated",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"member_id": str(member_id)},
        )

    # Tell the nominee they were selected. Dispatched after commit so the
    # worker reads the persisted nomination; failure to queue must not roll
    # back the nomination itself (mirrors the attestation notification path).
    try:
        dispatch_project_notification.delay(
            user_id=str(nominee_user_id),
            notification_type="org_attestor_trial_nominated",
            title="You've been nominated for a trial attestation",
            body=(
                "Your organization has nominated you to complete a trial "
                "attestation on its behalf. Open the attestor page to begin."
            ),
            payload={
                "org_id": str(org_id),
                "application_id": str(application.id),
            },
            link=f"/dashboard/organizations/{org_id}/attestor",
            dedupe_key=f"org_attestor_trial_nominated:{application.id}:{member_id}",
        )
    except Exception as exc:  # pragma: no cover - defensive queue guard
        logger.bind(
            module="organizations",
            action="nominate_trial_member",
            org_id=org_id,
            member_id=member_id,
        ).error("notification_dispatch_failed", error=str(exc))
    return application


# ---------------------------------------------------------------------------
# Platform-admin review pipeline and capability activation
# ---------------------------------------------------------------------------


async def _load_admin_application(
    db: AsyncSession,
    application_id: UUID,
) -> OrgAttestorApplication:
    """Load and lock one org attestor application by id, or raise 404."""
    application = await db.scalar(
        select(OrgAttestorApplication)
        .where(OrgAttestorApplication.id == application_id)
        .with_for_update()
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Org attestor application not found.",
        )
    return application


def _download_name_from_key(key: str) -> str:
    """Recover the original file name from a minted ``{uuid4}-{name}`` S3 key."""
    segment = key.rsplit("/", 1)[-1]
    if len(segment) > _UUID_KEY_PREFIX_LEN and segment[_UUID_KEY_PREFIX_LEN - 1] == "-":
        return segment[_UUID_KEY_PREFIX_LEN:]
    return segment


async def admin_list_documents(
    db: AsyncSession,
    *,
    application_id: UUID,
    admin_id: UUID,
) -> list[OrgAttestorDocumentLink]:
    """Return presigned GET links for an application's KYB and tax documents.

    KYB (incorporation) and tax documents live in the private artifacts bucket,
    so a reviewing platform admin can only open them through short-lived
    presigned GET URLs generated on demand (BR-level: private S3, presigned
    delivery only). Each incorporation document and the tax document, when
    present, yields one labelled link carrying its original file name. The
    access is audited.

    Args:
        db: Async session.
        application_id: Application whose documents to surface.
        admin_id: Authenticated platform admin requesting the links.

    Returns:
        A list of presigned download links, empty when no documents exist.

    Raises:
        HTTPException(404): If the application does not exist.
    """
    if db.in_transaction():
        await db.rollback()
    settings = get_settings()
    bucket = settings.s3_artifacts_bucket

    def _link(label: str, key: str) -> OrgAttestorDocumentLink:
        """Build a link for one key, signing only when the object exists.

        A reserved key whose upload never completed has no backing object, so
        signing a GET would resolve to an S3 ``NoSuchKey`` page. Verify first
        and hand back an unavailable placeholder instead of a broken link.
        """
        filename = _download_name_from_key(key)
        if not s3.storage.object_exists(bucket, key):
            return OrgAttestorDocumentLink(
                label=label, filename=filename, url="", available=False
            )
        return OrgAttestorDocumentLink(
            label=label,
            filename=filename,
            url=s3.storage.presigned_get(
                bucket, key, DOCUMENT_DOWNLOAD_TTL_SECONDS, download_name=filename
            ),
        )

    async with db.begin():
        application = await _load_admin_application(db, application_id)
        links: list[OrgAttestorDocumentLink] = []
        for index, key in enumerate(application.incorporation_doc_keys, start=1):
            links.append(_link(f"Incorporation document {index}", key))
        if application.tax_document_key is not None:
            tax_type = application.tax_document_type or "document"
            links.append(
                _link(f"Tax document ({tax_type})", application.tax_document_key)
            )
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_attestor_documents_viewed",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={
                "org_id": str(application.org_id),
                "document_count": len(links),
            },
        )
    logger.bind(
        module="organizations",
        action="admin_list_documents",
        user_id=admin_id,
        org_id=application.org_id,
    ).info("org_attestor_documents_viewed", document_count=len(links))
    return links


def _org_profile_specializations(application: OrgAttestorApplication) -> list[str]:
    """Derive legacy-matcher specializations from onboarding taxonomy fields."""
    values: list[str] = []
    for item in [*application.sectors, *application.functions]:
        if item not in values:
            values.append(item)
    return values


def _missing_approval_gates(
    application: OrgAttestorApplication,
    *,
    trial_passed: bool,
) -> list[str]:
    """Return any unsatisfied approval gates for an org application."""
    missing: list[str] = []
    if application.kyb_verified_at is None:
        missing.append("kyb_verified")
    if application.coi_signed_at is None:
        missing.append("undertakings_coi")
    if application.confidentiality_signed_at is None:
        missing.append("undertakings_confidentiality")
    if application.payout_account_id is None:
        missing.append("payout_account")
    if not application.tax_document_key:
        missing.append("tax_document")
    if not trial_passed:
        missing.append("trial_passed")
    if not application.sectors:
        missing.append("sectors")
    if not application.functions:
        missing.append("functions")
    return missing


async def admin_list_applications(
    db: AsyncSession,
    *,
    status_filter: str | None,
    page: int,
    page_size: int,
) -> tuple[list[OrgAttestorApplication], int]:
    """Return a page of org attestor applications for admin review.

    Args:
        db: Async session.
        status_filter: Optional status to filter the queue by.
        page: 1-indexed page number.
        page_size: Rows per page.

    Returns:
        A tuple of the page's applications and the total row count.
    """
    base = select(OrgAttestorApplication)
    if status_filter is not None:
        base = base.where(OrgAttestorApplication.status == status_filter)
    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    )
    rows = (
        await db.scalars(
            base.order_by(OrgAttestorApplication.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), int(total or 0)


async def admin_trial_states(
    db: AsyncSession,
    application_ids: Sequence[UUID],
) -> dict[UUID, str]:
    """Return the latest calibration-trial status per application.

    A ``passed`` trial always wins; otherwise the highest-attempt trial's
    status is reported. Applications with no trial are absent from the map.

    Args:
        db: Async session.
        application_ids: Applications to resolve trial state for.

    Returns:
        Mapping of application id to its trial status enum value.
    """
    if not application_ids:
        return {}
    result = await db.execute(
        select(
            AttestorTrial.org_application_id,
            AttestorTrial.status,
        )
        .where(AttestorTrial.org_application_id.in_(application_ids))
        .order_by(AttestorTrial.attempt.asc())
    )
    states: dict[UUID, str] = {}
    for app_id, trial_status in result:
        if app_id is None or states.get(app_id) == "passed":
            continue
        states[app_id] = trial_status
    return states


async def admin_verify_kyb(
    db: AsyncSession,
    *,
    application_id: UUID,
    admin_id: UUID,
) -> OrgAttestorApplication:
    """Stamp the KYB-verified gate on a submitted/needs-info application.

    Raises:
        HTTPException(404): If the application does not exist.
        HTTPException(409): If the application is not under review.
    """
    if db.in_transaction():
        await db.rollback()
    settings = get_settings()
    bucket = settings.s3_artifacts_bucket
    async with db.begin():
        application = await _load_admin_application(db, application_id)
        if application.status not in ("submitted", "needs_info"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only applications under review can be KYB-verified.",
            )
        # Never certify KYB against documents that were reserved but never
        # uploaded; the object must exist in storage before the gate can pass.
        keys = [*application.incorporation_doc_keys]
        if application.tax_document_key is not None:
            keys.append(application.tax_document_key)
        if any(not s3.storage.object_exists(bucket, key) for key in keys):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "One or more KYB/tax documents were not fully uploaded to "
                    "storage. Ask the organization to re-upload before verifying."
                ),
            )
        application.kyb_verified_at = datetime.now(UTC)
        application.kyb_verified_by = admin_id
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_attestor_kyb_verified",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"org_id": str(application.org_id)},
        )
    return application


async def admin_needs_info(
    db: AsyncSession,
    *,
    application_id: UUID,
    admin_id: UUID,
    feedback: str,
) -> OrgAttestorApplication:
    """Return a submitted application to the org for more information.

    Raises:
        HTTPException(404): If the application does not exist.
        HTTPException(409): If the application is not in ``submitted``.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await _load_admin_application(db, application_id)
        if application.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted applications can be sent back for info.",
            )
        now = datetime.now(UTC)
        application.status = "needs_info"
        application.admin_feedback = feedback
        application.reviewed_by = admin_id
        application.reviewed_at = now
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_attestor_needs_info",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"org_id": str(application.org_id)},
        )
    return application


async def admin_start_trial(
    db: AsyncSession,
    *,
    application_id: UUID,
    admin_id: UUID,
) -> AttestorTrial:
    """Assign the calibration trial to the nominated org member.

    Raises:
        HTTPException(404): If the application does not exist.
        HTTPException(409): If the application is not under review.
        HTTPException(422): If no trial member has been nominated.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await _load_admin_application(db, application_id)
        if application.status not in ("submitted", "needs_info"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only applications under review can start a trial.",
            )
        if application.trial_member_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nominate a trial member before starting the trial.",
            )
        nominee = await db.scalar(
            select(OrgMember).where(OrgMember.id == application.trial_member_id)
        )
        if nominee is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Nominated trial member not found.",
            )
        nominee_user_id = nominee.user_id
        org_id = application.org_id
        attempts = await db.scalar(
            select(func.count())
            .select_from(AttestorTrial)
            .where(AttestorTrial.org_application_id == application_id)
        )
        trial = AttestorTrial(
            org_application_id=application_id,
            org_id=application.org_id,
            member_id=application.trial_member_id,
            status="assigned",
            attempt=int(attempts or 0) + 1,
        )
        db.add(trial)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_attestor_trial_assigned",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"trial_id": str(trial.id), "attempt": trial.attempt},
        )
        trial_id = trial.id

    # Tell the nominee the trial is now actionable. Nomination only stamped the
    # member; this is the first moment there is work to do. Dispatched after
    # commit so the worker reads the persisted trial; a queue failure must not
    # roll back the assignment (mirrors nominate_trial_member).
    try:
        dispatch_project_notification.delay(
            user_id=str(nominee_user_id),
            notification_type="org_attestor_trial_assigned",
            title="Your trial attestation is ready",
            body=(
                "A trial attestation has been assigned to you on behalf of your "
                "organization. Open the attestor page to begin."
            ),
            payload={
                "org_id": str(org_id),
                "application_id": str(application_id),
                "trial_id": str(trial_id),
            },
            link=f"/dashboard/organizations/{org_id}/attestor",
            dedupe_key=f"org_attestor_trial_assigned:{trial_id}",
        )
    except Exception as exc:  # pragma: no cover - defensive queue guard
        logger.bind(
            module="organizations",
            action="admin_start_trial",
            org_id=org_id,
            trial_id=trial_id,
        ).error("notification_dispatch_failed", error=str(exc))
    return trial


async def _create_org_profile(
    db: AsyncSession,
    application: OrgAttestorApplication,
    approved_at: datetime,
) -> None:
    """Create or refresh the org's live attestor matching profile."""
    specializations = _org_profile_specializations(application)
    profile = await db.scalar(
        select(OrgAttestorProfile)
        .where(OrgAttestorProfile.org_id == application.org_id)
        .with_for_update()
    )
    if profile is None:
        profile = OrgAttestorProfile(
            org_id=application.org_id,
            specializations=specializations,
            jurisdictions=application.jurisdictions,
            sectors=application.sectors,
            functions=application.functions,
            active=True,
            verification_level=4,
            approved_at=approved_at,
            coi_declarations=application.coi_declarations,
            coi_signed_at=application.coi_signed_at,
            coi_expires_at=application.coi_expires_at,
            confidentiality_signed_at=application.confidentiality_signed_at,
        )
        db.add(profile)
        return
    profile.specializations = specializations
    profile.jurisdictions = application.jurisdictions
    profile.sectors = application.sectors
    profile.functions = application.functions
    profile.active = True
    profile.verification_level = 4
    profile.approved_at = approved_at
    profile.coi_declarations = application.coi_declarations
    profile.coi_signed_at = application.coi_signed_at
    profile.coi_expires_at = application.coi_expires_at
    profile.confidentiality_signed_at = application.confidentiality_signed_at


async def _sync_org_member_roles(db: AsyncSession, org_id: UUID) -> None:
    """Re-evaluate the derived attestor role for every member of an org.

    Imported lazily to avoid a module import cycle with the org service.
    ``sync_derived_roles`` manages its own transaction, so this must run
    after the caller's own transaction has committed.
    """
    from app.modules.organizations import service as org_service

    member_ids = (
        await db.scalars(
            select(OrgMember.user_id).where(OrgMember.org_id == org_id)
        )
    ).all()
    for user_id in member_ids:
        await org_service.sync_derived_roles(db, user_id=user_id)


async def admin_approve(
    db: AsyncSession,
    *,
    application_id: UUID,
    admin_id: UUID,
) -> OrgAttestorApplication:
    """Approve a fully gated application and activate the org attestor capability.

    In one transaction: transitions the application to ``approved``, creates or
    refreshes the org attestor profile, and activates the attestor capability.
    Then, after commit, re-evaluates the derived attestor role for every member
    (the derived-role sync reads the now-committed active capability).

    Raises:
        HTTPException(404): If the application does not exist.
        HTTPException(409): If the application is not ``submitted``.
        HTTPException(422): If any approval gate is unsatisfied.
    """
    if db.in_transaction():
        await db.rollback()
    now = datetime.now(UTC)
    async with db.begin():
        application = await _load_admin_application(db, application_id)
        if application.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only submitted applications can be approved.",
            )
        trial_passed = await _trial_passed(db, application.id)
        missing = _missing_approval_gates(application, trial_passed=trial_passed)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Missing approval gates: {', '.join(missing)}.",
            )

        await _create_org_profile(db, application, now)

        capability = await db.scalar(
            select(OrgCapability)
            .where(
                OrgCapability.org_id == application.org_id,
                OrgCapability.capability == "attestor",
            )
            .with_for_update()
        )
        if capability is None:
            capability = OrgCapability(
                org_id=application.org_id,
                capability="attestor",
                status="active",
                activated_at=now,
            )
            db.add(capability)
        else:
            capability.status = "active"
            capability.activated_at = now

        application.status = "approved"
        application.reviewed_by = admin_id
        application.reviewed_at = now
        org_id = application.org_id
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_attestor_activated",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"org_id": str(org_id), "verification_level": 4},
        )

    await _sync_org_member_roles(db, org_id)
    await db.refresh(application)
    logger.bind(
        module="organizations",
        action="org_attestor_activated",
        user_id=str(admin_id),
    ).info("Org attestor capability activated")
    return application


async def admin_reject(
    db: AsyncSession,
    *,
    application_id: UUID,
    admin_id: UUID,
    feedback: str,
) -> OrgAttestorApplication:
    """Terminally reject an org attestor application under review.

    Raises:
        HTTPException(404): If the application does not exist.
        HTTPException(409): If the application is already approved or rejected.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await _load_admin_application(db, application_id)
        if application.status in ("approved", "rejected"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Application has already been decided.",
            )
        now = datetime.now(UTC)
        application.status = "rejected"
        application.admin_feedback = feedback
        application.reviewed_by = admin_id
        application.reviewed_at = now
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="org_attestor_application_rejected",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"org_id": str(application.org_id)},
        )
    return application


async def admin_set_capability_status(
    db: AsyncSession,
    *,
    org_id: UUID,
    admin_id: UUID,
    status_value: Literal["suspended", "active", "revoked"],
) -> None:
    """Suspend, reinstate, or revoke an org's attestor capability.

    Revocation marks the matching profile inactive; suspension leaves the
    profile intact (matching filters on the capability status). Reinstatement
    reactivates the profile. Every member's derived attestor role is then
    re-evaluated after commit.

    Raises:
        HTTPException(404): If the org has no attestor capability.
    """
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        capability = await db.scalar(
            select(OrgCapability)
            .where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == "attestor",
            )
            .with_for_update()
        )
        if capability is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Org attestor capability not found.",
            )
        capability.status = status_value
        profile = await db.scalar(
            select(OrgAttestorProfile)
            .where(OrgAttestorProfile.org_id == org_id)
            .with_for_update()
        )
        if profile is not None:
            if status_value == "revoked":
                profile.active = False
            elif status_value == "active":
                profile.active = True
        await write_audit(
            db=db,
            actor_id=admin_id,
            action=f"org_attestor_capability_{status_value}",
            target_type="organization",
            target_id=org_id,
            metadata={"status": status_value},
        )

    await _sync_org_member_roles(db, org_id)
    logger.bind(
        module="organizations",
        action="org_attestor_capability_status",
        user_id=str(admin_id),
    ).info("Org attestor capability status changed")
