"""Admin service logic."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User, UserRole


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
