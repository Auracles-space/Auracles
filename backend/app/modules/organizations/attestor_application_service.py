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

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.application_service import (
    TAX_DOCUMENT_MAX_BYTES,
    TAX_DOCUMENT_UPLOAD_TTL_SECONDS,
)
from app.modules.attestation.credential_service import _safe_file_name
from app.modules.attestation.models import AttestorTrial
from app.modules.attestation.schemas import CredentialEvidenceUploadSessionResponse
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.financials.models import PayoutAccount
from app.modules.organizations import nda_service
from app.modules.organizations.models import (
    OrgAttestorApplication,
    OrgCapability,
    OrgMember,
)
from app.modules.organizations.schemas import (
    OrgAttestorApplicationCreateRequest,
    OrgAttestorApplicationUpdateRequest,
    OrgAttestorGateChecklist,
    OrgAttestorTaxDocumentRequest,
    OrgUndertakingsSignRequest,
)

# CoI/confidentiality validity window; mirrors the individual attestor flow
# (application_service.sign_coi stamps coi_expires_at one year out).
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
                # Legacy NOT NULL column superseded by sectors/framework_categories.
                specializations=[],
                legal_name=payload.legal_name,
                registration_number=payload.registration_number,
                incorporation_doc_keys=payload.incorporation_doc_keys,
                sectors=payload.sectors,
                framework_categories=payload.framework_categories,
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
        and application.framework_categories
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
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_attestor_trial_member_nominated",
            target_type="org_attestor_application",
            target_id=application.id,
            metadata={"member_id": str(member_id)},
        )
    return application
