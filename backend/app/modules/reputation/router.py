"""FastAPI router for reputation reads (Phase 5e).

Framework and contributor reputation are public; operator reputation is gated
to the operator, an in-deal contributor, or an admin. All payloads expose
factor labels only — never weights or raw sub-values.

Maps to: BR-ATT-005, full-spec section 3234.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_token_payload, get_current_user
from app.modules.auth.models import User
from app.modules.reputation import service
from app.modules.reputation.schemas import ReputationResponse
from app.shared.schemas.token import TokenPayload

router = APIRouter(prefix="/reputation", tags=["Reputation"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


async def _read_or_404(
    db: AsyncSession, *, subject_type: str, subject_id: UUID
) -> ReputationResponse:
    """Return a reputation response or raise 404 when the subject is unknown."""
    payload = await service.read_reputation(
        db, subject_type=subject_type, subject_id=subject_id
    )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reputation subject not found.",
        )
    return ReputationResponse.model_validate(payload)


@router.get(
    "/framework/{framework_id}",
    response_model=ReputationResponse,
    summary="Get a framework's public reputation",
)
async def get_framework_reputation(
    framework_id: UUID,
    db: DatabaseSession,
) -> ReputationResponse:
    """Return the public reputation score + factor labels for one framework."""
    return await _read_or_404(db, subject_type="framework", subject_id=framework_id)


@router.get(
    "/contributor/{contributor_id}",
    response_model=ReputationResponse,
    summary="Get a contributor's public reputation",
)
async def get_contributor_reputation(
    contributor_id: UUID,
    db: DatabaseSession,
) -> ReputationResponse:
    """Return the public reputation score + factor labels for one contributor."""
    return await _read_or_404(
        db, subject_type="contributor", subject_id=contributor_id
    )


@router.get(
    "/operator/{operator_id}",
    response_model=ReputationResponse,
    summary="Get an operator's reputation (gated)",
)
async def get_operator_reputation(
    operator_id: UUID,
    db: DatabaseSession,
    user: Annotated[User, Depends(get_current_user)],
    payload: Annotated[TokenPayload, Depends(get_current_token_payload)],
) -> ReputationResponse:
    """Return an operator's reputation to self, an in-deal contributor, or admin.

    Raises:
        HTTPException(403): Requester is not entitled to this operator's score.
        HTTPException(404): Operator subject does not exist.
    """
    visible = await service.operator_reputation_visible(
        db,
        operator_id=operator_id,
        requester_id=user.id,
        requester_roles=payload.roles,
    )
    if not visible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator reputation is not visible to you.",
        )
    return await _read_or_404(db, subject_type="operator", subject_id=operator_id)
