"""Attestor application service logic.

This slice handles Attestor onboarding applications and admin review. Later
attestation slices consume approved `attestor_profiles` for matching.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation.models import AttestorApplication, AttestorProfile
from app.modules.attestation.schemas import (
    AttestorApplicationCreateRequest,
    AttestorApplicationReviewRequest,
    AttestorApplicationUpdateRequest,
)
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole


async def submit_application(
    db: AsyncSession,
    user: User,
    payload: AttestorApplicationCreateRequest,
) -> AttestorApplication:
    """Create one pending Attestor application for the authenticated user."""
    user_id = user.id
    existing_pending = await db.scalar(
        select(AttestorApplication).where(
            AttestorApplication.user_id == user_id,
            AttestorApplication.status == "pending",
        )
    )
    if existing_pending is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending Attestor application.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = AttestorApplication(
            user_id=user_id,
            specializations=payload.specializations,
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
    """Withdraw a pending Attestor application owned by the current user."""
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
        if application.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending Attestor applications can be withdrawn.",
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
    """Edit a pending Attestor application owned by the current user.

    Only the owner may edit, and only while the application is still pending
    (before an admin acts on it). Approved, rejected, or withdrawn applications
    are immutable; the user re-applies instead.

    Args:
        db: Async session.
        user: Authenticated owner of the application.
        application_id: Application to edit.
        payload: Replacement application fields.

    Returns:
        The updated, still-pending application.

    Raises:
        HTTPException(404): If the application does not exist for this user.
        HTTPException(422): If the application is no longer pending.
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
        if application.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending Attestor applications can be edited.",
            )

        application.specializations = payload.specializations
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
    """Approve or reject a pending Attestor application with admin 2FA."""
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
        if application.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending Attestor applications can be reviewed.",
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
