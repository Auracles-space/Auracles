"""Attestation clarification requests with SLA-pause accounting.

The assigned Attestor may ask the Requestor up to two clarifying questions.
Each open clarification extends the completion SLA by the full response window
up front so the overdue-revocation beat never fires mid-clarification.

Maps to: design spec section 4.4.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.attestation import notifications as attestation_notifications
from app.modules.attestation.models import AttestationClarification
from app.modules.attestation.workspace_service import load_workspace_attestation
from app.modules.auth.models import User
from app.modules.financials.models import PlatformConfig

CLARIFICATION_RESPONSE_HOURS_DEFAULT = 48
MAX_CLARIFICATIONS = 2


async def _response_hours(db: AsyncSession) -> int:
    """Read the configured clarification response window in hours.

    Args:
        db: Async database session.

    Returns:
        Positive clarification response window in hours.

    Raises:
        HTTPException: 500 when the platform configuration is non-integer or
            below the minimum allowed value.
    """
    configured = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "attestation_clarification_response_hours"
        )
    )
    if configured is None:
        return CLARIFICATION_RESPONSE_HOURS_DEFAULT
    try:
        parsed = int(configured)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="attestation_clarification_response_hours is invalid.",
        ) from exc
    if parsed < 1:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="attestation_clarification_response_hours is invalid.",
        )
    return parsed


async def send_clarification(
    db: AsyncSession,
    *,
    attestor: User,
    attestation_id: UUID,
    question: str,
    now: datetime | None = None,
) -> AttestationClarification:
    """Send one attestor-to-requestor clarification and extend the SLA window.

    Args:
        db: Async database session.
        attestor: Authenticated assigned attestor.
        attestation_id: Workspace attestation receiving the clarification.
        question: Clarification question text.
        now: Optional timestamp override for deterministic tests.

    Returns:
        The persisted clarification row.

    Raises:
        HTTPException: 404 on assignee mismatch, 409 outside `in_review`, or
            422 when a clarification is already open or the two-question limit
            has been exhausted.
    """
    current_time = now or datetime.now(UTC)
    attestor_id = attestor.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        attestation = await load_workspace_attestation(
            db,
            attestation_id=attestation_id,
            attestor_id=attestor_id,
            allowed_statuses={"in_review"},
        )
        total = await db.scalar(
            select(func.count()).select_from(AttestationClarification).where(
                AttestationClarification.attestation_id == attestation.id
            )
        )
        if total is not None and total >= MAX_CLARIFICATIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Clarification limit reached for this assignment.",
            )
        open_count = await db.scalar(
            select(func.count()).select_from(AttestationClarification).where(
                AttestationClarification.attestation_id == attestation.id,
                AttestationClarification.status == "open",
            )
        )
        if open_count:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="An open clarification is already awaiting a response.",
            )

        response_hours = await _response_hours(db)
        response_due_at = current_time + timedelta(hours=response_hours)
        clarification = AttestationClarification(
            attestation_id=attestation.id,
            question=question,
            sent_at=current_time,
            response_due_at=response_due_at,
            status="open",
        )
        db.add(clarification)
        if attestation.completion_due_at is not None:
            attestation.completion_due_at = attestation.completion_due_at + timedelta(
                hours=response_hours
            )
        await write_audit(
            db=db,
            actor_id=attestor_id,
            action="attestation_clarification_sent",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"response_hours": response_hours},
        )
        await db.flush()

    await db.refresh(clarification)
    attestation_notifications.notify_clarification_requested(
        attestation,
        requestor_id=attestation.requestor_id,
    )
    return clarification
