"""Shared License grant rules.

Granting a License for a Framework priced at zero happens on three paths —
individual checkout, organization checkout, and the Partner API — none of
which can import the others. Seat allocation has the same problem: it is a
property of the license tier, not of the rail that paid for it, and it was
already copied into the webhook handler and Collection settlement before this
module existed.

This module imports nothing from the financials, webhooks, or developer
packages, so every grant path can share it without a cycle.

Maps to: FR-FWK-014, FR-FIN-004.
"""

from __future__ import annotations

from uuid import UUID

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.rate_limit import RateLimiter, RedisCounter
from app.modules.frameworks.models import License

# A free acquisition has no charge in front of it, and a License is all a
# review needs. Without a ceiling, one person could take a free Framework on
# many accounts and farm its rating. Set for someone collecting what they
# actually want to read in a day, not for building a review farm.
FREE_LICENSE_RATE_LIMITER = RateLimiter(
    namespace="free_license", limit=10, window=86400
)


def license_seats_total(license_type: str) -> int | None:
    """Return the default seat allocation for a purchased license tier.

    Args:
        license_type: The license tier being granted.

    Returns:
        The seat count, or None for tiers that are not seat-limited.
    """
    if license_type == "single_user":
        return 1
    if license_type == "team":
        return 10
    return None


async def grant_free_license(
    db: AsyncSession,
    redis: RedisCounter,
    *,
    framework_id: UUID,
    version_at_grant: str,
    license_type: str,
    operator_id: UUID | None,
    licensee_org_id: UUID | None,
    actor_id: UUID,
    module: str,
    action: str,
    audit_metadata: dict[str, str] | None = None,
) -> UUID:
    """Grant a License for a Framework priced at zero and return its id.

    Written in-request because there is no provider callback to wait for. No
    Transaction is created — not even a zero-amount one — so the money tables
    keep their positive-amount guarantees and nothing reaches commission,
    invoicing, or payouts. Refunds are keyed by transaction id, which makes a
    free licence structurally unrefundable.

    Takes plain values rather than a loaded `Framework` on purpose: callers
    reach this after helpers that roll back and restart the shared session,
    which expires an ORM instance and turns a later attribute read into a
    lazy load with no greenlet to run it.

    Every caller must have already run its full purchase guard sequence
    (published, seller active, not self-dealing, no existing License, tier
    offered). This grants unconditionally.

    Args:
        db: Session. The caller must not hold an open transaction.
        redis: Counter backing the per-acquirer rate limit.
        framework_id: The Framework being granted, already validated.
        version_at_grant: The Framework version the licence is pinned to.
        license_type: The requested tier, already checked against the listing.
        operator_id: Individual acquirer, or None for an organization.
        licensee_org_id: Acquiring organization, or None for an individual.
        actor_id: The person who performed this, which is the org admin rather
            than the licence holder on the organization path.
        module: Log module name of the calling path.
        action: Log and audit action name of the calling path.
        audit_metadata: Extra audit fields, such as the Partner attribution
            that has no revenue row to live on.

    Returns:
        The id of the granted License.

    Raises:
        HTTPException(429): The acquirer is over the free-acquisition ceiling.
    """
    rate_limit_key = str(operator_id or licensee_org_id)
    await FREE_LICENSE_RATE_LIMITER.check(redis, rate_limit_key)

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        license_row = License(
            framework_id=framework_id,
            operator_id=operator_id,
            licensee_org_id=licensee_org_id,
            transaction_id=None,
            license_type=license_type,
            status="active",
            version_at_grant=version_at_grant,
            seats_used=1,
            seats_total=license_seats_total(license_type),
        )
        db.add(license_row)
        await db.flush()
        license_id = license_row.id
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="free_license_granted",
            target_type="license",
            target_id=license_id,
            metadata={
                "framework_id": str(framework_id),
                "license_type": license_type,
                "version_at_grant": version_at_grant,
                **({"org_id": str(licensee_org_id)} if licensee_org_id else {}),
                **(audit_metadata or {}),
            },
        )

    logger.bind(
        module=module,
        action=action,
        user_id=actor_id,
        framework_id=framework_id,
    ).info("free_license_granted")
    return license_id
