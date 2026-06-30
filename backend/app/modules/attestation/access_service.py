"""Attestation access-package entitlement, presigned access, and audit (§2.5).

Entitlement is derived from live Attestation/Offer status — never stored — so
revocation is automatic. Full content access additionally requires the per-accept
content-use acknowledgment recorded on the attestation row.

Maps to: FR §2.5 (Framework Access Package).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import Attestation, AttestationOffer
from app.modules.auth.models import User

AccessScope = Literal["preview", "full", "none"]

FULL_ACCESS_STATUSES = frozenset({"accepted", "report_submitted", "disputed"})


async def attestation_access_scope(
    db: AsyncSession,
    *,
    attestation: Attestation,
    user: User,
) -> AccessScope:
    """Compute a user's access scope for an attestation's framework content.

    Entitlement is derived entirely from live status — no grant table exists.
    Full access requires the assigned attestor to be in a review-active status
    *and* to have recorded a content-use acknowledgment. Preview is granted to
    any cohort member holding a live "offered" offer. All other callers get none.

    Args:
        db: Async session for querying offer status.
        attestation: The attestation whose content is being accessed.
        user: The requesting user.

    Returns:
        "full" for the assigned attestor in a review state with an acknowledgment,
        "preview" for a cohort member holding a live offer, otherwise "none".
    """
    # Full: assigned attestor + review-active status + content-use ack
    if (
        attestation.attestor_id == user.id
        and attestation.status in FULL_ACCESS_STATUSES
        and attestation.content_ack_at is not None
    ):
        return "full"

    # Preview: cohort member with a live "offered" offer
    offer_status = await db.scalar(
        select(AttestationOffer.status).where(
            AttestationOffer.attestation_id == attestation.id,
            AttestationOffer.attestor_id == user.id,
        )
    )
    if offer_status == "offered":
        return "preview"

    return "none"
