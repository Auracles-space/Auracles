"""Rating service for attestation reports (Module 5 section 5.3)."""

from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation, AttestationRating
from app.modules.auth.models import User


async def submit_rating(
    db: AsyncSession,
    requestor: User,
    attestation_id: UUID,
    stars: int,
    comment: str | None = None,
) -> AttestationRating:
    """Submit a 1-5 quality rating for a stood attestation report.

    Validates that the rating user is the attestation's requestor (404),
    the attestation is fully closed and approved (409), and no prior
    rating exists (409).

    Args:
        db: Async SQLAlchemy session.
        requestor: The currently authenticated user.
        attestation_id: The UUID of the attestation to rate.
        stars: Rating between 1 and 5.
        comment: Optional text comment.

    Returns:
        The newly persisted AttestationRating.

    Raises:
        HTTPException(404): If attestation not found or user is not requestor.
        HTTPException(409): If not closed/approved, or already rated.
    """
    attestation = await db.get(Attestation, attestation_id)
    if not attestation or attestation.requestor_id != requestor.id:
        logger.bind(
            module="attestation",
            action="submit_rating",
            user_id=requestor.id,
            attestation_id=attestation_id,
        ).warning("access_denied: not requestor or not found")
        raise HTTPException(status_code=404, detail="Attestation not found")

    if attestation.status != "closed" or attestation.outcome != "approved":
        logger.bind(
            module="attestation",
            action="submit_rating",
            user_id=requestor.id,
            attestation_id=attestation_id,
        ).warning("rating_denied: attestation not closed and approved")
        raise HTTPException(
            status_code=409,
            detail="Only closed, approved attestations can be rated",
        )

    # Enforce uniqueness explicitly before constraint hit to return 409
    existing = await db.scalar(
        select(AttestationRating).where(
            AttestationRating.attestation_id == attestation_id
        )
    )
    if existing:
        logger.bind(
            module="attestation",
            action="submit_rating",
            user_id=requestor.id,
            attestation_id=attestation_id,
        ).warning("rating_denied: duplicate rating")
        raise HTTPException(
            status_code=409,
            detail="Attestation has already been rated",
        )

    rating = AttestationRating(
        attestation_id=attestation_id,
        rated_by=requestor.id,
        stars=stars,
        comment=comment,
    )
    db.add(rating)
    await db.flush()

    logger.bind(
        module="attestation",
        action="submit_rating",
        user_id=requestor.id,
        attestation_id=attestation_id,
    ).info(f"attestation_rated_with_{stars}_stars")

    return rating
