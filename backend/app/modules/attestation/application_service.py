"""Attestor application service logic.

This slice handles Attestor onboarding applications and admin review. Later
attestation slices consume approved `attestor_profiles` for matching.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.credential_service import (
    CREDENTIAL_EVIDENCE_MAX_BYTES,
    CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS,
    _safe_file_name,
)
from app.modules.attestation.models import (
    AttestationUploadSession,
    AttestorApplication,
    AttestorProfile,
    AttestorTrial,
    Credential,
)
from app.modules.attestation.schemas import (
    AttestorApplicationCreateRequest,
    AttestorApplicationReviewRequest,
    AttestorApplicationUpdateRequest,
    AttestorCredentialCheckRequest,
    AttestorTaxDocumentRequest,
    CoiDeclarationRequest,
    CredentialEvidenceUploadSessionResponse,
)
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PayoutAccount

TAX_DOCUMENT_UPLOAD_TTL_SECONDS = CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS
TAX_DOCUMENT_MAX_BYTES = CREDENTIAL_EVIDENCE_MAX_BYTES


async def _load_locked_application(
    db: AsyncSession,
    application_id: UUID,
) -> AttestorApplication:
    """Load and lock an Attestor application or raise a typed not-found error."""
    application = await db.scalar(
        select(AttestorApplication)
        .where(AttestorApplication.id == application_id)
        .with_for_update()
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestor application not found.",
        )
    return application


async def submit_application(
    db: AsyncSession,
    user: User,
    payload: AttestorApplicationCreateRequest,
) -> AttestorApplication:
    """Create one submitted Attestor application for the authenticated user."""
    user_id = user.id
    existing_submitted = await db.scalar(
        select(AttestorApplication).where(
            AttestorApplication.user_id == user_id,
            AttestorApplication.status == "submitted",
        )
    )
    if existing_submitted is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a submitted Attestor application.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = AttestorApplication(
            user_id=user_id,
            status="submitted",
            # Legacy NOT NULL column superseded by `sectors`/`framework_categories`;
            # left empty for new onboarding applications (see taxonomy.py).
            specializations=[],
            legal_name=payload.legal_name,
            linkedin_url=payload.linkedin_url,
            professional_body_numbers=payload.professional_body_numbers,
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
            actor_id=user_id,
            action="attestor_application_submitted",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"status": application.status},
        )
    return application


async def list_my_applications(
    db: AsyncSession,
    user: User,
) -> list[AttestorApplication]:
    """Return the authenticated user's Attestor application history."""
    result = await db.execute(
        select(AttestorApplication)
        .where(AttestorApplication.user_id == user.id)
        .order_by(AttestorApplication.created_at.desc())
    )
    return list(result.scalars().all())


async def withdraw_application(
    db: AsyncSession,
    user: User,
    application_id: UUID,
) -> AttestorApplication:
    """Withdraw a submitted Attestor application owned by the current user."""
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await db.scalar(
            select(AttestorApplication)
            .where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == user_id,
            )
            .with_for_update()
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestor application not found.",
            )
        if application.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only submitted Attestor applications can be withdrawn.",
            )

        application.status = "withdrawn"
        await write_audit(
            db=db,
            actor_id=user_id,
            action="attestor_application_withdrawn",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"status": application.status},
        )
    return application


async def update_application(
    db: AsyncSession,
    user: User,
    application_id: UUID,
    payload: AttestorApplicationUpdateRequest,
) -> AttestorApplication:
    """Edit a submitted Attestor application owned by the current user.

    Only the owner may edit, and only while the application is still
    submitted (before an admin acts on it). Approved, rejected, or withdrawn
    applications are immutable; the user re-applies instead.

    Args:
        db: Async session.
        user: Authenticated owner of the application.
        application_id: Application to edit.
        payload: Replacement application fields.

    Returns:
        The updated, still-submitted application.

    Raises:
        HTTPException(404): If the application does not exist for this user.
        HTTPException(422): If the application is no longer submitted.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await db.scalar(
            select(AttestorApplication)
            .where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == user_id,
            )
            .with_for_update()
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestor application not found.",
            )
        if application.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only submitted Attestor applications can be edited.",
            )

        application.legal_name = payload.legal_name
        application.linkedin_url = payload.linkedin_url
        application.professional_body_numbers = payload.professional_body_numbers
        application.sectors = payload.sectors
        application.framework_categories = payload.framework_categories
        application.jurisdictions = payload.jurisdictions
        application.credentials_summary = payload.credentials_summary
        application.sample_work = payload.sample_work
        application.professional_references = payload.professional_references
        await write_audit(
            db=db,
            actor_id=user_id,
            action="attestor_application_updated",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"status": application.status},
        )
    return application


async def sign_coi(
    db: AsyncSession,
    user: User,
    application_id: UUID,
    payload: CoiDeclarationRequest,
) -> AttestorApplication:
    """Sign or refresh an applicant's conflict-of-interest declaration.

    Args:
        db: Async session.
        user: Authenticated owner of the application.
        application_id: Application whose declaration is being signed.
        payload: Declared conflicts and policy acceptance flag.

    Returns:
        The application with updated CoI declaration fields.

    Raises:
        HTTPException(404): If the application does not exist for this user.
        HTTPException(422): If policy acceptance is missing or the application
            is active.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await db.scalar(
            select(AttestorApplication)
            .where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == user_id,
            )
            .with_for_update()
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestor application not found.",
            )
        if not payload.accept_policy:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="CoI policy must be accepted.",
            )
        if application.status == "active":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="CoI declarations are locked once the application is active.",
            )

        now = datetime.now(UTC)
        application.coi_declarations = [
            declaration.model_dump() for declaration in payload.declarations
        ]
        application.coi_signed_at = now
        application.coi_expires_at = now + timedelta(days=365)
        await write_audit(
            db=db,
            actor_id=user_id,
            action="attestor_coi_signed",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"declaration_count": len(payload.declarations)},
        )
    return application


async def attach_payout(
    db: AsyncSession,
    user: User,
    application_id: UUID,
    payout_account_id: UUID,
) -> AttestorApplication:
    """Attach an owned payout account to an Attestor application.

    Args:
        db: Async session.
        user: Authenticated owner of the application.
        application_id: Application to update.
        payout_account_id: Owned payout account to attach.

    Returns:
        The application with its payout account attached.

    Raises:
        HTTPException(404): If the application or payout account is not found.
        HTTPException(422): If the application is already active.
    """
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await db.scalar(
            select(AttestorApplication)
            .where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == user_id,
            )
            .with_for_update()
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestor application not found.",
            )
        if application.status == "active":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Payout settings are locked once the application is active.",
            )
        payout_account = await db.scalar(
            select(PayoutAccount).where(
                PayoutAccount.id == payout_account_id,
                PayoutAccount.user_id == user_id,
                PayoutAccount.deleted_at.is_(None),
            )
        )
        if payout_account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout account not found.",
            )

        application.payout_account_id = payout_account_id
        await write_audit(
            db=db,
            actor_id=user_id,
            action="attestor_payout_attached",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"payout_account_id": str(payout_account_id)},
        )
    return application


async def set_tax_document(
    db: AsyncSession,
    user: User,
    application_id: UUID,
    payload: AttestorTaxDocumentRequest,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned upload session for an applicant's tax document.

    Args:
        db: Async session.
        user: Authenticated owner of the application.
        application_id: Application whose tax document is being set.
        payload: Upload metadata and declared tax document type.

    Returns:
        A presigned POST upload session response for the tax document.

    Raises:
        HTTPException(404): If the application does not exist for this user.
        HTTPException(413): If the upload exceeds the size limit.
        HTTPException(422): If the application is already active.
    """
    user_id = user.id
    if payload.size_bytes > TAX_DOCUMENT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Tax document upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=TAX_DOCUMENT_UPLOAD_TTL_SECONDS)
    key = (
        f"attestor-tax-documents/{application_id}/{user_id}/{uuid4()}-"
        f"{_safe_file_name(payload.file_name)}"
    )
    async with db.begin():
        application = await db.scalar(
            select(AttestorApplication)
            .where(
                AttestorApplication.id == application_id,
                AttestorApplication.user_id == user_id,
            )
            .with_for_update()
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attestor application not found.",
            )
        if application.status == "active":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Tax documents are locked once the application is active.",
            )

        upload_session = AttestationUploadSession(
            application_id=application_id,
            user_id=user_id,
            purpose="attestor_tax_document",
            s3_key=key,
            content_type=payload.content_type,
            size_limit=TAX_DOCUMENT_MAX_BYTES,
            scan_status="pending_scan",
            expires_at=expires_at,
        )
        db.add(upload_session)
        application.tax_document_type = payload.tax_document_type
        application.tax_document_key = key
        await db.flush()
        await db.refresh(upload_session)
        await write_audit(
            db=db,
            actor_id=user_id,
            action="attestor_tax_document_set",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"tax_document_type": payload.tax_document_type},
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
        id=upload_session.id,
        s3_key=key,
        url=str(post["url"]),
        fields={str(key_): str(value) for key_, value in post["fields"].items()},
        expires_at=expires_at,
        size_limit=TAX_DOCUMENT_MAX_BYTES,
        scan_status=upload_session.scan_status,
    )


async def list_applications_for_admin(
    db: AsyncSession,
    status_filter: str | None,
) -> list[AttestorApplication]:
    """Return Attestor applications for admin review, optionally by status."""
    query = select(AttestorApplication).order_by(AttestorApplication.created_at.desc())
    if status_filter is not None:
        query = query.where(AttestorApplication.status == status_filter)
    result = await db.execute(query)
    return list(result.scalars().all())


async def review_application(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    application_id: UUID,
    payload: AttestorApplicationReviewRequest,
) -> AttestorApplication:
    """Approve or reject a submitted Attestor application with admin 2FA."""
    admin_id = admin.id
    now = datetime.now(UTC)
    feedback = payload.feedback.strip() if payload.feedback else None
    if payload.decision == "rejected" and not feedback:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Feedback is required when rejecting an Attestor application.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        locked_admin = await db.get(User, admin_id, with_for_update=True)
        if locked_admin is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_admin,
            code=payload.totp_code,
        )

        application = await _load_locked_application(db, application_id)
        if application.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only submitted Attestor applications can be reviewed.",
            )

        application.status = payload.decision
        application.admin_feedback = feedback
        application.reviewed_by = admin_id
        application.reviewed_at = now

        if payload.decision == "approved":
            await _approve_attestor_profile_and_role(
                db=db,
                application=application,
                admin_id=admin_id,
                approved_at=now,
            )

        await write_audit(
            db=db,
            actor_id=admin_id,
            action=f"attestor_application_{payload.decision}",
            target_type="attestor_application",
            target_id=application.id,
            metadata={
                "user_id": str(application.user_id),
                "status": application.status,
            },
        )
    return application


async def verify_kyc(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    application_id: UUID,
    name_match: bool,
    totp_code: str,
) -> AttestorApplication:
    """Confirm KYC and name match, advancing a submitted application to Level 1."""
    admin_id = admin.id
    now = datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        locked_admin = await db.get(User, admin_id, with_for_update=True)
        if locked_admin is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_admin,
            code=totp_code,
        )

        application = await _load_locked_application(db, application_id)
        if application.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only submitted applications can be KYC-verified.",
            )

        applicant = await db.get(User, application.user_id)
        if applicant is None or applicant.kyc_status != "verified":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Applicant KYC is not verified.",
            )
        if not name_match:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="KYC name does not match.",
            )

        application.status = "identity_verified"
        application.kyc_verified_at = now
        application.kyc_name_match = True
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestor_kyc_verified",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"user_id": str(application.user_id)},
        )
    return application


async def verify_credential(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    application_id: UUID,
    payload: AttestorCredentialCheckRequest,
) -> AttestorApplication:
    """Cross-check one applicant credential and advance Level 2/3 on success."""
    admin_id = admin.id
    now = datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        locked_admin = await db.get(User, admin_id, with_for_update=True)
        if locked_admin is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_admin,
            code=payload.totp_code,
        )

        application = await _load_locked_application(db, application_id)
        if application.status != "identity_verified":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Only identity-verified applications can have credentials checked."
                ),
            )

        credential = await db.scalar(
            select(Credential).where(
                Credential.id == payload.credential_id,
                Credential.user_id == application.user_id,
            )
        )
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credential does not belong to this applicant.",
            )

        credential.issuing_body = payload.issuing_body
        credential.good_standing = payload.good_standing
        credential.registry_checked_at = now
        credential.registry_checked_by = admin_id
        credential.registry_reference = payload.registry_reference

        if not payload.good_standing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credential not in good standing.",
            )

        application.status = "professional_verified"
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestor_credential_checked",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"credential_id": str(payload.credential_id)},
        )
    return application


async def assign_trial(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    application_id: UUID,
    seeded_framework_id: UUID | None,
    totp_code: str,
) -> AttestorTrial:
    """Assign a stubbed calibration trial to a professional-verified application."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        locked_admin = await db.get(User, admin_id, with_for_update=True)
        if locked_admin is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_admin,
            code=totp_code,
        )

        application = await _load_locked_application(db, application_id)
        existing = await db.scalar(
            select(func.count())
            .select_from(AttestorTrial)
            .where(AttestorTrial.application_id == application_id)
        )
        attempt_count = int(existing or 0)
        if attempt_count >= 2:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Trial attempts exhausted; application held.",
            )
        if application.status != "professional_verified":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Only professional-verified applications can be assigned a trial."
                ),
            )

        trial = AttestorTrial(
            application_id=application_id,
            seeded_framework_id=seeded_framework_id,
            status="assigned",
            attempt=attempt_count + 1,
        )
        db.add(trial)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestor_trial_assigned",
            target_type="attestor_application",
            target_id=application.id,
            metadata={"trial_id": str(trial.id), "attempt": trial.attempt},
        )
    return trial


async def decide_trial(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    application_id: UUID,
    trial_id: UUID,
    passed: bool,
    feedback: str | None,
    totp_code: str,
) -> AttestorApplication:
    """Decide a stubbed calibration trial and advance or hold the application."""
    admin_id = admin.id
    now = datetime.now(UTC)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        locked_admin = await db.get(User, admin_id, with_for_update=True)
        if locked_admin is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=locked_admin,
            code=totp_code,
        )

        application = await _load_locked_application(db, application_id)
        trial = await db.scalar(
            select(AttestorTrial)
            .where(
                AttestorTrial.id == trial_id,
                AttestorTrial.application_id == application_id,
            )
            .with_for_update()
        )
        if trial is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trial not found.",
            )
        if trial.status != "assigned":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Trial already decided.",
            )

        trial.decided_by = admin_id
        trial.decided_at = now
        trial.feedback = feedback

        if passed:
            trial.status = "passed"
            application.status = "expert_verified"
            await write_audit(
                db=db,
                actor_id=admin_id,
                action="attestor_trial_passed",
                target_type="attestor_application",
                target_id=application.id,
                metadata={"trial_id": str(trial.id)},
            )
            return application

        trial.status = "failed"
        metadata = {"trial_id": str(trial.id), "attempt": trial.attempt}
        if trial.attempt >= 2:
            application.status = "held"
            await write_audit(
                db=db,
                actor_id=admin_id,
                action="attestor_application_held",
                target_type="attestor_application",
                target_id=application.id,
                metadata=metadata,
            )
            return application

        await write_audit(
            db=db,
            actor_id=admin_id,
            action="attestor_trial_failed",
            target_type="attestor_application",
            target_id=application.id,
            metadata=metadata,
        )
    return application


async def _approve_attestor_profile_and_role(
    db: AsyncSession,
    application: AttestorApplication,
    admin_id: UUID,
    approved_at: datetime,
) -> None:
    """Copy an approved application into matcher profile and role state."""
    role = await db.scalar(
        select(UserRole)
        .where(
            UserRole.user_id == application.user_id,
            UserRole.role == "attestor",
        )
        .with_for_update()
    )
    if role is None:
        role = UserRole(user_id=application.user_id, role="attestor")
        db.add(role)
    role.approved_at = approved_at
    role.approved_by = admin_id

    profile = await db.scalar(
        select(AttestorProfile)
        .where(AttestorProfile.user_id == application.user_id)
        .with_for_update()
    )
    if profile is None:
        profile = AttestorProfile(
            user_id=application.user_id,
            specializations=application.specializations,
            jurisdictions=application.jurisdictions,
            active=True,
            approved_at=approved_at,
        )
        db.add(profile)
        return

    profile.specializations = application.specializations
    profile.jurisdictions = application.jurisdictions
    profile.active = True
    profile.approved_at = approved_at
