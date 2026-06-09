"""Admin service logic."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.integrations import stripe
from app.integrations.stripe import StripeProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import KycDocument, User, UserRole
from app.modules.financials import escrow_service
from app.modules.financials.models import Escrow, Transaction
from app.modules.frameworks.models import Framework, License
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


async def grant_license(
    db: AsyncSession,
    admin: User,
    framework_id: UUID,
    operator_id: UUID,
    license_type: str,
    expires_at: datetime | None,
    seats_total: int | None,
) -> License:
    """Grant an Operator license to a Framework for Phase 2 admin flows."""
    admin_id = admin.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await db.scalar(
            select(Framework).where(Framework.id == framework_id)
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        operator = await db.scalar(select(User).where(User.id == operator_id))
        if operator is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Operator not found.",
            )
        existing = await db.scalar(
            select(License).where(
                License.framework_id == framework_id,
                License.operator_id == operator_id,
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operator already has a license for this Framework.",
            )

        resolved_seats_total = seats_total
        if license_type == "team" and resolved_seats_total is None:
            resolved_seats_total = 10
        license_row = License(
            framework_id=framework.id,
            operator_id=operator.id,
            license_type=license_type,
            status="active",
            version_at_grant=framework.version,
            expires_at=expires_at,
            seats_used=1,
            seats_total=resolved_seats_total,
        )
        db.add(license_row)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=admin_id,
            action="license_granted",
            target_type="license",
            target_id=license_row.id,
            metadata={
                "framework_id": str(framework.id),
                "operator_id": str(operator.id),
                "version_at_grant": framework.version,
                "type": license_type,
            },
        )
    return license_row


async def _verify_admin_2fa(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    totp_code: str,
) -> None:
    """Require a valid admin TOTP or backup code before escrow override."""
    await auth_service.verify_totp_for_sensitive_action(
        db=db,
        redis=redis,
        user=admin,
        code=totp_code,
    )
    await db.commit()


async def release_escrow_override(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    escrow_id: UUID,
    reason: str,
    totp_code: str,
) -> Escrow:
    """Release held escrow funds through an audited admin override."""
    admin_id = admin.id
    await _verify_admin_2fa(db=db, redis=redis, admin=admin, totp_code=totp_code)
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        escrow = await escrow_service.release(
            db,
            escrow_id=escrow_id,
            actor_id=admin_id,
            reason=reason,
            admin_override=True,
        )
    return escrow


async def refund_escrow_override(
    db: AsyncSession,
    redis: Redis,
    admin: User,
    escrow_id: UUID,
    reason: str,
    totp_code: str,
) -> Escrow:
    """Refund held escrow funds through an audited admin override."""
    admin_id = admin.id
    await _verify_admin_2fa(db=db, redis=redis, admin=admin, totp_code=totp_code)

    escrow = await db.get(Escrow, escrow_id)
    if escrow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escrow not found.",
        )
    if escrow.status == "refunded":
        return escrow
    if escrow.status == "released":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Released escrow cannot be refunded.",
        )
    transaction = await db.get(Transaction, escrow.transaction_id)
    if transaction is None or transaction.provider_ref is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escrow funding transaction is missing provider metadata.",
        )
    if transaction.provider != "stripe":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unsupported escrow payment provider.",
        )
    try:
        await stripe.create_refund(
            payment_intent_id=transaction.provider_ref,
            amount=transaction.amount,
            currency=transaction.currency,
            idempotency_key=f"escrow_refund:{escrow_id}",
        )
    except StripeProviderError as exc:
        logger.bind(
            module="admin",
            action="refund_escrow_override",
            user_id=admin_id,
            escrow_id=escrow_id,
        ).error("stripe_escrow_refund_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider is unavailable.",
        ) from exc

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        escrow = await escrow_service.refund(
            db,
            escrow_id=escrow_id,
            actor_id=admin_id,
            reason=reason,
            admin_override=True,
        )
    return escrow
