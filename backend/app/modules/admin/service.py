"""Admin service logic."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import KycDocument, User, UserRole
from app.modules.frameworks.models import Framework
from app.workers.tasks.processing.minhash_index import (
    remove_framework_artifacts_from_index,
)


async def assign_user_role(
    db: AsyncSession,
    admin: User,
    target_user_id: UUID,
    role: str,
) -> UserRole:
    """Assign a user role, approving Attestor when an admin performs it."""
    target = await db.scalar(select(User).where(User.id == target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    existing = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == target_user_id,
            UserRole.role == role,
        )
    )
    if existing is None:
        existing = UserRole(user_id=target_user_id, role=role)
        db.add(existing)

    existing.approved_at = datetime.now(UTC)
    existing.approved_by = admin.id
    action = "attestor_approved" if role == "attestor" else "role_assigned"
    await write_audit(
        db=db,
        actor_id=admin.id,
        action=action,
        target_type="user",
        target_id=target_user_id,
        metadata={"role": role},
    )
    await db.commit()
    return existing


async def review_user_kyc(
    db: AsyncSession,
    admin: User,
    target_user_id: UUID,
    review_status: str,
    notes: str | None,
) -> KycDocument:
    """Review the latest KYC document and update the user's KYC status."""
    target = await db.scalar(select(User).where(User.id == target_user_id))
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    document = await db.scalar(
        select(KycDocument)
        .where(KycDocument.user_id == target_user_id)
        .order_by(desc(KycDocument.created_at))
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KYC document not found.",
        )

    document.status = review_status
    document.reviewed_by = admin.id
    document.reviewed_at = datetime.now(UTC)
    document.notes = notes
    target.kyc_status = review_status
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="kyc_status_change",
        target_type="user",
        target_id=target_user_id,
        metadata={"status": review_status, "document_id": str(document.id)},
    )
    await db.commit()
    return document


async def suspend_framework(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    reason: str,
) -> Framework:
    """Suspend a published Framework after admin moderation review."""
    framework = await db.scalar(select(Framework).where(Framework.id == framework_id))
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    if framework.status == "suspended":
        return framework
    if framework.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only published Frameworks can be suspended.",
        )

    framework.status = "suspended"
    framework.rejection_reason = reason.strip()
    await write_audit(
        db=db,
        actor_id=admin.id,
        action="framework_suspended",
        target_type="framework",
        target_id=framework.id,
        metadata={"reason": framework.rejection_reason},
    )
    await db.commit()
    try:
        await remove_framework_artifacts_from_index(framework.id)
    except Exception as exc:
        logger.bind(
            module="admin",
            action="remove_framework_from_lsh",
            user_id=admin.id,
            framework_id=framework.id,
        ).error("artifact_lsh_remove_failed", error=str(exc))
    return framework
