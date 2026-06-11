"""Developer application service logic.

This slice handles Developer onboarding applications and admin review. Later
Phase 5a slices consume approved `developer_accounts` for API keys, partner
purchase attribution, commissions, webhooks, and analytics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth import service as auth_service
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import DeveloperAccount, DeveloperApplication
from app.modules.developer.schemas import (
    DeveloperApplicationCreateRequest,
    DeveloperApplicationReviewRequest,
)


async def submit_application(
    db: AsyncSession,
    user: User,
    payload: DeveloperApplicationCreateRequest,
) -> DeveloperApplication:
    """Create one pending Developer application for the authenticated user."""
    user_id = user.id
    existing_pending = await db.scalar(
        select(DeveloperApplication).where(
            DeveloperApplication.user_id == user_id,
            DeveloperApplication.status == "pending",
        )
    )
    if existing_pending is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending Developer application.",
        )

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = DeveloperApplication(
            user_id=user_id,
            company_name=payload.company_name,
            website=str(payload.website) if payload.website else None,
            use_case=payload.use_case,
        )
        db.add(application)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=user_id,
            action="developer_application_submitted",
            target_type="developer_application",
            target_id=application.id,
            metadata={"status": application.status},
        )
    return application


async def list_my_applications(
    db: AsyncSession,
    user: User,
) -> list[DeveloperApplication]:
    """Return the authenticated user's Developer application history."""
    result = await db.execute(
        select(DeveloperApplication)
        .where(DeveloperApplication.user_id == user.id)
        .order_by(DeveloperApplication.created_at.desc())
    )
    return list(result.scalars().all())


async def withdraw_application(
    db: AsyncSession,
    user: User,
    application_id: UUID,
) -> DeveloperApplication:
    """Withdraw a pending Developer application owned by the current user."""
    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        application = await db.scalar(
            select(DeveloperApplication)
            .where(
                DeveloperApplication.id == application_id,
                DeveloperApplication.user_id == user_id,
            )
            .with_for_update()
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Developer application not found.",
            )
        if application.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending Developer applications can be withdrawn.",
            )

        application.status = "withdrawn"
        await write_audit(
            db=db,
            actor_id=user_id,
            action="developer_application_withdrawn",
            target_type="developer_application",
            target_id=application.id,
            metadata={"status": application.status},
        )
    return application


async def list_applications_for_admin(
    db: AsyncSession,
    status_filter: Literal["pending", "approved", "rejected", "withdrawn"] | None,
) -> list[DeveloperApplication]:
    """Return Developer applications for admin review, optionally by status."""
    query = select(DeveloperApplication).order_by(
        DeveloperApplication.created_at.desc()
    )
    if status_filter is not None:
        query = query.where(DeveloperApplication.status == status_filter)
    result = await db.execute(query)
    return list(result.scalars().all())


async def review_application(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    application_id: UUID,
    payload: DeveloperApplicationReviewRequest,
) -> DeveloperApplication:
    """Approve or reject a pending Developer application with admin 2FA."""
    admin_id = admin.id
    now = datetime.now(UTC)
    feedback = payload.feedback.strip() if payload.feedback else None
    if payload.decision == "rejected" and not feedback:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Feedback is required when rejecting a Developer application.",
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
            select(DeveloperApplication)
            .where(DeveloperApplication.id == application_id)
            .with_for_update()
        )
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Developer application not found.",
            )
        if application.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only pending Developer applications can be reviewed.",
            )

        application.status = payload.decision
        application.admin_feedback = feedback
        application.reviewed_by = admin_id
        application.reviewed_at = now

        if payload.decision == "approved":
            await _approve_developer_account_and_role(
                db=db,
                application=application,
                admin_id=admin_id,
                approved_at=now,
            )

        await write_audit(
            db=db,
            actor_id=admin_id,
            action=f"developer_application_{payload.decision}",
            target_type="developer_application",
            target_id=application.id,
            metadata={
                "user_id": str(application.user_id),
                "status": application.status,
            },
        )
    return application


async def _approve_developer_account_and_role(
    db: AsyncSession,
    application: DeveloperApplication,
    admin_id: UUID,
    approved_at: datetime,
) -> None:
    """Copy an approved application into account and role state."""
    role = await db.scalar(
        select(UserRole)
        .where(
            UserRole.user_id == application.user_id,
            UserRole.role == "developer",
        )
        .with_for_update()
    )
    if role is None:
        role = UserRole(user_id=application.user_id, role="developer")
        db.add(role)
    role.approved_at = approved_at
    role.approved_by = admin_id

    account = await db.scalar(
        select(DeveloperAccount)
        .where(DeveloperAccount.user_id == application.user_id)
        .with_for_update()
    )
    if account is None:
        account = DeveloperAccount(
            user_id=application.user_id,
            application_id=application.id,
            company_name=application.company_name,
            commission_tier=1,
            tier_rate=Decimal("0.0500"),
            tier_sales_count=0,
            approved_at=approved_at,
        )
        db.add(account)
        return

    account.status = "active"
    account.application_id = application.id
    account.company_name = application.company_name
    account.approved_at = approved_at
