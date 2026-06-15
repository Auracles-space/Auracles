"""GDPR account-deletion request and cooling-off scheduling service.

Handles password-confirmed deletion scheduling, active-request lookup, and the
status read model used by the authenticated settings surface.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import verify_password
from app.modules.attestation.models import Attestation, AttestationDispute
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.developer.models import DeveloperAccount, PartnerPayout
from app.modules.financials.models import Escrow, Payout, PlatformConfig
from app.modules.gdpr.models import AccountDeletionRequest
from app.modules.gdpr.schemas import (
    AccountDeletionBlockedReason,
    AccountDeletionRequestBody,
    AccountDeletionStatusResponse,
)
from app.modules.projects.models import Dispute, Milestone, Project, Proposal

ACTIVE_DELETION_STATUSES = {"pending", "scheduled"}
ACTIVE_DISPUTE_STATUSES = ("open", "under_review")
ACTIVE_PROJECT_STATUSES = ("assigned", "in_progress", "delivered", "disputed")
ACTIVE_ATTESTATION_STATUSES = (
    "pending_fee",
    "matching",
    "offered",
    "accepted",
    "report_submitted",
    "disputed",
    "needs_admin",
    "resolved",
)


def _status_response(
    request: AccountDeletionRequest | None,
) -> AccountDeletionStatusResponse:
    """Convert a deletion-request row into the public response shape."""
    if request is None:
        return AccountDeletionStatusResponse(
            id=None,
            status=None,
            blocked_reasons=[],
            scheduled_for=None,
            requested_at=None,
            completed_at=None,
        )
    blocked_reasons = cast(list[dict[str, object]] | None, request.blocked_reasons)
    return AccountDeletionStatusResponse(
        id=request.id,
        status=request.status,
        blocked_reasons=[
            AccountDeletionBlockedReason.model_validate(reason)
            for reason in blocked_reasons or []
        ],
        scheduled_for=request.scheduled_for,
        requested_at=request.requested_at,
        completed_at=request.completed_at,
    )


async def _account_deletion_grace_days(db: AsyncSession) -> int:
    """Return the configured cooling-off period with safe defaults."""
    configured = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "account_deletion_grace_days"
        )
    )
    if configured is None:
        return 14
    try:
        days = int(configured)
    except ValueError:
        return 14
    return min(max(days, 1), 30)


async def _latest_request(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> AccountDeletionRequest | None:
    """Return the latest deletion request for one user, if any."""
    return cast(
        "AccountDeletionRequest | None",
        await db.scalar(
            select(AccountDeletionRequest)
            .where(AccountDeletionRequest.user_id == user_id)
            .order_by(
                AccountDeletionRequest.requested_at.desc(),
                AccountDeletionRequest.id.desc(),
            )
            .limit(1)
        ),
    )


async def _ensure_password_confirmation(
    *,
    user: User,
    payload: AccountDeletionRequestBody,
) -> None:
    """Require password confirmation for current password-account users."""
    password_hash = user.password_hash
    if password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Passwordless account deletion re-auth is not available yet.",
        )
    if not verify_password(payload.password.get_secret_value(), password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password.",
        )


async def _count_held_escrows(db: AsyncSession, user_id: UUID) -> int:
    """Return how many held escrows still involve the current user."""
    project_count = int(
        await db.scalar(
            select(func.count(func.distinct(Escrow.id)))
            .select_from(Escrow)
            .join(
                Milestone,
                Milestone.id == Escrow.ref_id,
            )
            .join(Project, Project.id == Milestone.project_id)
            .join(Proposal, Proposal.id == Project.accepted_proposal_id)
            .where(
                Escrow.ref_type == "project_milestone",
                Escrow.status == "held",
                or_(
                    Project.operator_id == user_id,
                    Proposal.contributor_id == user_id,
                ),
            )
        )
        or 0
    )
    attestation_count = int(
        await db.scalar(
            select(func.count(func.distinct(Escrow.id)))
            .select_from(Escrow)
            .join(
                Attestation,
                Attestation.id == Escrow.ref_id,
            )
            .where(
                Escrow.ref_type == "attestation",
                Escrow.status == "held",
                or_(
                    Attestation.requestor_id == user_id,
                    Attestation.attestor_id == user_id,
                ),
            )
        )
        or 0
    )
    return project_count + attestation_count


async def _count_pending_payouts(db: AsyncSession, user_id: UUID) -> int:
    """Return how many pending or processing payout flows still involve the user."""
    contributor_count = int(
        await db.scalar(
            select(func.count(Payout.id)).where(
                Payout.contributor_id == user_id,
                Payout.status.in_(("pending", "processing")),
            )
        )
        or 0
    )
    partner_count = int(
        await db.scalar(
            select(func.count(PartnerPayout.id))
            .select_from(PartnerPayout)
            .join(
                DeveloperAccount,
                DeveloperAccount.id == PartnerPayout.developer_account_id,
            )
            .where(
                DeveloperAccount.user_id == user_id,
                PartnerPayout.status.in_(("pending", "processing")),
            )
        )
        or 0
    )
    return contributor_count + partner_count


async def _count_open_disputes(db: AsyncSession, user_id: UUID) -> int:
    """Return active project and attestation disputes involving the user."""
    project_count = int(
        await db.scalar(
            select(func.count(func.distinct(Dispute.id)))
            .select_from(Dispute)
            .join(Project, Project.id == Dispute.project_id)
            .join(Proposal, Proposal.id == Project.accepted_proposal_id)
            .where(
                Dispute.status.in_(ACTIVE_DISPUTE_STATUSES),
                or_(
                    Project.operator_id == user_id,
                    Proposal.contributor_id == user_id,
                ),
            )
        )
        or 0
    )
    attestation_count = int(
        await db.scalar(
            select(func.count(func.distinct(AttestationDispute.id)))
            .select_from(AttestationDispute)
            .join(Attestation, Attestation.id == AttestationDispute.attestation_id)
            .where(
                AttestationDispute.status.in_(ACTIVE_DISPUTE_STATUSES),
                or_(
                    Attestation.requestor_id == user_id,
                    Attestation.attestor_id == user_id,
                ),
            )
        )
        or 0
    )
    return project_count + attestation_count


async def _count_active_projects(db: AsyncSession, user_id: UUID) -> int:
    """Return active accepted projects involving the user."""
    return int(
        await db.scalar(
            select(func.count(func.distinct(Project.id)))
            .select_from(Project)
            .join(Proposal, Proposal.id == Project.accepted_proposal_id)
            .where(
                Project.status.in_(ACTIVE_PROJECT_STATUSES),
                or_(
                    Project.operator_id == user_id,
                    Proposal.contributor_id == user_id,
                ),
            )
        )
        or 0
    )


async def _count_active_attestations(db: AsyncSession, user_id: UUID) -> int:
    """Return non-terminal attestations involving the user."""
    return int(
        await db.scalar(
            select(func.count(func.distinct(Attestation.id))).where(
                Attestation.status.in_(ACTIVE_ATTESTATION_STATUSES),
                or_(
                    Attestation.requestor_id == user_id,
                    Attestation.attestor_id == user_id,
                ),
            )
        )
        or 0
    )


async def collect_blocked_reasons(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> list[AccountDeletionBlockedReason]:
    """Return all active obligations that block GDPR account deletion."""
    reasons: list[AccountDeletionBlockedReason] = []
    held_escrow_count = await _count_held_escrows(db, user_id)
    if held_escrow_count > 0:
        reasons.append(
            AccountDeletionBlockedReason(
                code="held_escrow",
                message="Resolve held escrow before requesting account deletion.",
                count=held_escrow_count,
            )
        )
    pending_payout_count = await _count_pending_payouts(db, user_id)
    if pending_payout_count > 0:
        reasons.append(
            AccountDeletionBlockedReason(
                code="pending_payout",
                message=(
                    "Wait for pending payouts to settle before requesting "
                    "account deletion."
                ),
                count=pending_payout_count,
            )
        )
    open_dispute_count = await _count_open_disputes(db, user_id)
    if open_dispute_count > 0:
        reasons.append(
            AccountDeletionBlockedReason(
                code="open_dispute",
                message="Resolve open disputes before requesting account deletion.",
                count=open_dispute_count,
            )
        )
    active_project_count = await _count_active_projects(db, user_id)
    if active_project_count > 0:
        reasons.append(
            AccountDeletionBlockedReason(
                code="in_progress_project",
                message="Close active projects before requesting account deletion.",
                count=active_project_count,
            )
        )
    active_attestation_count = await _count_active_attestations(db, user_id)
    if active_attestation_count > 0:
        reasons.append(
            AccountDeletionBlockedReason(
                code="active_attestation",
                message="Close active attestations before requesting account deletion.",
                count=active_attestation_count,
            )
        )
    return reasons


async def request_account_deletion(
    *,
    db: AsyncSession,
    redis: Redis,
    user: User,
    payload: AccountDeletionRequestBody,
) -> tuple[AccountDeletionStatusResponse, int]:
    """Schedule account deletion after password confirmation and cooling-off."""
    await _ensure_password_confirmation(user=user, payload=payload)

    user_id = user.id
    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            active_request = await db.scalar(
                select(AccountDeletionRequest).where(
                    AccountDeletionRequest.user_id == user_id,
                    AccountDeletionRequest.status.in_(ACTIVE_DELETION_STATUSES),
                )
            )
            if active_request is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Account deletion is already pending.",
                )

            user_for_confirmation = await db.get(User, user_id, with_for_update=True)
            if user_for_confirmation is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid access token.",
                )
            if user_for_confirmation.totp_enabled:
                await auth_service.verify_totp_for_sensitive_action(
                    db=db,
                    redis=redis,
                    user=user_for_confirmation,
                    code=payload.totp_code,
                )
            reasons = await collect_blocked_reasons(db=db, user_id=user_id)
            if reasons:
                request = AccountDeletionRequest(
                    user_id=user_id,
                    status="blocked",
                    blocked_reasons=[
                        reason.model_dump(mode="json") for reason in reasons
                    ],
                )
                db.add(request)
                await db.flush()
                await write_audit(
                    db=db,
                    actor_id=user_id,
                    action="account_deletion_blocked",
                    target_type="account_deletion_request",
                    target_id=request.id,
                    metadata={
                        "reason_codes": [reason.code for reason in reasons],
                    },
                )
                return _status_response(request), status.HTTP_409_CONFLICT

            grace_days = await _account_deletion_grace_days(db)
            request = AccountDeletionRequest(
                user_id=user_id,
                status="scheduled",
                blocked_reasons=[],
                scheduled_for=datetime.now(UTC) + timedelta(days=grace_days),
            )
            db.add(request)
            await db.flush()
            await write_audit(
                db=db,
                actor_id=user_id,
                action="account_deletion_requested",
                target_type="account_deletion_request",
                target_id=request.id,
            )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account deletion is already pending.",
        ) from exc

    return (
        await get_account_deletion_status(db=db, user_id=user_id),
        status.HTTP_202_ACCEPTED,
    )


async def get_account_deletion_status(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> AccountDeletionStatusResponse:
    """Return the latest GDPR account-deletion request for the current user."""
    return _status_response(await _latest_request(db=db, user_id=user_id))


async def cancel_account_deletion(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> AccountDeletionStatusResponse:
    """Cancel the current user's scheduled GDPR deletion during cooling-off."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        request = await db.scalar(
            select(AccountDeletionRequest)
            .where(
                AccountDeletionRequest.user_id == user_id,
                AccountDeletionRequest.status.in_(ACTIVE_DELETION_STATUSES),
            )
            .order_by(
                AccountDeletionRequest.requested_at.desc(),
                AccountDeletionRequest.id.desc(),
            )
            .with_for_update()
            .limit(1)
        )
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account deletion request not found.",
            )
        request.status = "cancelled"
        request.scheduled_for = None
        request.blocked_reasons = []
        await write_audit(
            db=db,
            actor_id=user_id,
            action="account_deletion_cancelled",
            target_type="account_deletion_request",
            target_id=request.id,
        )
    return await get_account_deletion_status(db=db, user_id=user_id)
