"""Per-subject reputation factor aggregators (normalized 0..1).

Each aggregator queries Phase 2-4 source tables and returns a mapping of factor
name to :class:`FactorResult` (normalized value in [0,1] plus evidence count).
Counts saturate against per-factor targets; 1-5 averages map linearly to [0,1];
fault-attributed penalties subtract from the relevant factor, bounded at 0.

Maps to: full-spec section 10 (reputation factors).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation.models import (
    SETTLED_ATTESTATION_STATUSES,
    Attestation,
    AttestationRating,
    AttestorWarning,
)
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework, License, Review
from app.modules.projects.models import Dispute, Project, Proposal
from app.modules.reputation.service import FactorResult
from app.modules.reputation.weights import ReputationConfig

_ADOPTION_TARGET = Decimal("25")  # active licenses to saturate framework adoption
_ORG_CONTRIBUTOR_PROJECT_TARGET = Decimal("5")
_ORG_CONTRIBUTOR_REVIEW_WEIGHT = Decimal("0.80")
_ORG_CONTRIBUTOR_PROJECT_WEIGHT = Decimal("0.20")
_SCORE_QUANT = Decimal("0.01")


def _avg_review_norm(avg: Decimal | None) -> Decimal:
    """Map a 1-5 average rating onto [0,1]; absent ratings score 0."""
    if avg is None:
        return Decimal("0")
    return max(Decimal("0"), min(Decimal("1"), (avg - Decimal("1")) / Decimal("4")))


def _saturating(count: int, target: Decimal) -> Decimal:
    """Return a saturating 0..1 score for a count against its target."""
    return min(Decimal("1"), Decimal(count) / target)


async def framework_factors(
    db: AsyncSession,
    framework_id: UUID,
    cfg: ReputationConfig,
) -> dict[str, FactorResult]:
    """Aggregate reputation factors for one framework."""
    avg, cnt = (
        await db.execute(
            select(func.avg(Review.score), func.count(Review.id)).where(
                Review.framework_id == framework_id
            )
        )
    ).one()
    review_count = int(cnt or 0)
    reviews = FactorResult(
        _avg_review_norm(Decimal(str(avg)) if avg is not None else None),
        review_count,
    )

    pos_att = int(
        await db.scalar(
            select(func.count(Attestation.id)).where(
                Attestation.target_type == "framework",
                Attestation.target_id == framework_id,
                Attestation.outcome.in_(("approved", "conditional")),
                Attestation.status.in_(
                    ("report_submitted", *SETTLED_ATTESTATION_STATUSES)
                ),
            )
        )
        or 0
    )
    rej_att = int(
        await db.scalar(
            select(func.count(Attestation.id)).where(
                Attestation.target_type == "framework",
                Attestation.target_id == framework_id,
                Attestation.outcome == "rejected",
            )
        )
        or 0
    )
    att_penalty = cfg.dispute_penalty * Decimal(rej_att)
    att_norm = _saturating(pos_att, Decimal("3")) - att_penalty
    attestations = FactorResult(
        max(Decimal("0"), min(Decimal("1"), att_norm)), pos_att + rej_att
    )

    active_licenses = int(
        await db.scalar(
            select(func.count(License.id)).where(
                License.framework_id == framework_id, License.status == "active"
            )
        )
        or 0
    )
    adoption = FactorResult(
        _saturating(active_licenses, _ADOPTION_TARGET), active_licenses
    )

    # completion + recency are real future factors but launch with zero weight.
    # They stay as explicit keys so the config shape stays stable during
    # recalibration.
    completion = FactorResult(Decimal("0.5"), 0)
    recency = FactorResult(Decimal("0.5"), 0)
    return {
        "reviews": reviews,
        "attestations": attestations,
        "adoption": adoption,
        "completion": completion,
        "recency": recency,
    }


async def contributor_factors(
    db: AsyncSession,
    user_id: UUID,
    cfg: ReputationConfig,
) -> dict[str, FactorResult]:
    """Aggregate reputation factors for one contributor."""
    from app.modules.auth.models import User, UserRole
    from app.modules.reputation.models import ReputationScore

    user = await db.get(User, user_id)
    kyc_ok = bool(user and getattr(user, "kyc_status", None) == "verified")
    attestor_ok = bool(
        await db.scalar(
            select(UserRole.id).where(
                UserRole.user_id == user_id,
                UserRole.role == "attestor",
                UserRole.approved_at.is_not(None),
            )
        )
    )
    verification = FactorResult(
        (Decimal("0.5") if kyc_ok else Decimal("0"))
        + (Decimal("0.5") if attestor_ok else Decimal("0")),
        (1 if kyc_ok else 0) + (1 if attestor_ok else 0),
    )

    fw_ids = (
        (
            await db.execute(
                select(Framework.id).where(
                    Framework.contributor_id == user_id,
                    Framework.status == "published",
                )
            )
        )
        .scalars()
        .all()
    )
    perf_val, perf_n = Decimal("0"), 0
    if fw_ids:
        avg_score = await db.scalar(
            select(func.avg(ReputationScore.score)).where(
                ReputationScore.subject_type == "framework",
                ReputationScore.subject_id.in_(fw_ids),
                ReputationScore.is_provisional.is_(False),
            )
        )
        if avg_score is not None:
            perf_val = Decimal(str(avg_score)) / Decimal("100")
            perf_n = len(fw_ids)
    framework_performance = FactorResult(perf_val, perf_n)

    avg_recv, cnt_recv = (
        await db.execute(
            select(func.avg(Review.score), func.count(Review.id))
            .join(Framework, Framework.id == Review.framework_id)
            .where(Framework.contributor_id == user_id)
        )
    ).one()
    reviews_received = FactorResult(
        _avg_review_norm(Decimal(str(avg_recv)) if avg_recv is not None else None),
        int(cnt_recv or 0),
    )

    pos_att = int(
        await db.scalar(
            select(func.count(Attestation.id)).where(
                Attestation.target_type == "contributor",
                Attestation.target_id == user_id,
                Attestation.outcome.in_(("approved", "conditional")),
                Attestation.status.in_(
                    ("report_submitted", *SETTLED_ATTESTATION_STATUSES)
                ),
            )
        )
        or 0
    )
    attestations_received = FactorResult(_saturating(pos_att, Decimal("2")), pos_att)

    proposals = int(
        await db.scalar(
            select(func.count(Proposal.id)).where(Proposal.contributor_id == user_id)
        )
        or 0
    )
    activity = FactorResult(_saturating(proposals, Decimal("10")), proposals)
    return {
        "verification": verification,
        "framework_performance": framework_performance,
        "reviews_received": reviews_received,
        "attestations_received": attestations_received,
        "activity": activity,
    }


async def org_contributor_reputation_score(
    db: AsyncSession,
    org_id: UUID,
) -> Decimal | None:
    """Aggregate the public reputation score for one contributor organization.

    The org profile exposes a lightweight public score, not a full
    ``reputation_scores`` subject. Reviews come from the org's published
    Frameworks; project signal comes from closed Projects whose accepted
    Proposal belongs to the org. Individual contributor reputation remains on
    the user subject path and is not modified here.
    """
    avg_review, review_count = (
        await db.execute(
            select(func.avg(Review.score), func.count(Review.id))
            .join(Framework, Framework.id == Review.framework_id)
            .where(
                Framework.contributor_org_id == org_id,
                Framework.status == "published",
            )
        )
    ).one()
    completed_project_count = int(
        await db.scalar(
            select(func.count(func.distinct(Project.id)))
            .join(Proposal, Proposal.id == Project.accepted_proposal_id)
            .where(
                Proposal.contributor_org_id == org_id,
                Proposal.status == "accepted",
                Project.status == "closed",
            )
        )
        or 0
    )
    if int(review_count or 0) == 0 and completed_project_count == 0:
        return None

    review_component = _avg_review_norm(
        Decimal(str(avg_review)) if avg_review is not None else None
    )
    project_component = _saturating(
        completed_project_count,
        _ORG_CONTRIBUTOR_PROJECT_TARGET,
    )
    score = (
        review_component * _ORG_CONTRIBUTOR_REVIEW_WEIGHT
        + project_component * _ORG_CONTRIBUTOR_PROJECT_WEIGHT
    ) * Decimal("100")
    return score.quantize(_SCORE_QUANT, rounding=ROUND_HALF_UP)


async def operator_factors(
    db: AsyncSession,
    user_id: UUID,
    cfg: ReputationConfig,
) -> dict[str, FactorResult]:
    """Aggregate reputation factors for one operator."""
    purchases = int(
        await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.payer_id == user_id,
                Transaction.transaction_type == "purchase",
                Transaction.status == "completed",
            )
        )
        or 0
    )
    purchase_activity = FactorResult(_saturating(purchases, Decimal("10")), purchases)

    active = int(
        await db.scalar(
            select(func.count(License.id)).where(
                License.operator_id == user_id, License.status == "active"
            )
        )
        or 0
    )
    revoked = int(
        await db.scalar(
            select(func.count(License.id)).where(
                License.operator_id == user_id, License.status == "revoked"
            )
        )
        or 0
    )
    total_lic = active + revoked
    compliance_val = (
        Decimal("0.5") if total_lic == 0 else (Decimal(active) / Decimal(total_lic))
    )
    license_compliance = FactorResult(compliance_val, total_lic)

    reviews_written = int(
        await db.scalar(
            select(func.count(Review.id)).where(Review.operator_id == user_id)
        )
        or 0
    )
    review_quality = FactorResult(
        _saturating(reviews_written, Decimal("5")), reviews_written
    )

    projects_created = int(
        await db.scalar(
            select(func.count(Project.id)).where(Project.operator_id == user_id)
        )
        or 0
    )
    lost_disputes = int(
        await db.scalar(
            select(func.count(Dispute.id))
            .join(Project, Project.id == Dispute.project_id)
            .where(
                Project.operator_id == user_id,
                Dispute.status == "resolved",
                Dispute.resolution_type == "refund",
            )
        )
        or 0
    )
    eng_val = max(
        Decimal("0"),
        _saturating(projects_created, Decimal("5"))
        - cfg.dispute_penalty * Decimal(lost_disputes),
    )
    engagement = FactorResult(eng_val, projects_created)
    return {
        "purchase_activity": purchase_activity,
        "license_compliance": license_compliance,
        "review_quality": review_quality,
        "engagement": engagement,
    }


async def org_attestor_factors(
    db: AsyncSession,
    org_id: UUID,
    cfg: ReputationConfig,
) -> dict[str, FactorResult]:
    """Aggregate reputation factors for one attestor organization.

    The org-level mirror of :func:`attestor_factors`: signals key on the
    organization's stood attestations (``attestor_org_id``), its requestor
    ratings, its upheld warnings, and its profile late-submission count. The
    reviewing member who staffed each review never enters the score.

    Args:
        db: Async SQLAlchemy session.
        org_id: Organization id of the attestor being scored.
        cfg: Loaded ``attestor_org`` reputation config.

    Returns:
        Mapping of ``rating`` and ``reliability`` factor results.
    """
    from app.modules.organizations.models import OrgAttestorProfile

    stood_attestation_ids = (
        select(Attestation.id)
        .where(
            Attestation.attestor_org_id == org_id,
            Attestation.status.in_(SETTLED_ATTESTATION_STATUSES),
            Attestation.report_published_eligible.is_(True),
        )
        .scalar_subquery()
    )

    avg_stars, rating_count = (
        await db.execute(
            select(
                func.avg(AttestationRating.stars),
                func.count(AttestationRating.id),
            ).where(AttestationRating.attestation_id.in_(stood_attestation_ids))
        )
    ).one()
    rating = FactorResult(
        _avg_review_norm(Decimal(str(avg_stars)) if avg_stars is not None else None),
        int(rating_count or 0),
    )

    stood_count = int(
        await db.scalar(
            select(func.count()).select_from(
                select(Attestation.id)
                .where(
                    Attestation.attestor_org_id == org_id,
                    Attestation.status.in_(SETTLED_ATTESTATION_STATUSES),
                    Attestation.report_published_eligible.is_(True),
                )
                .subquery()
            )
        )
        or 0
    )
    warning_count = int(
        await db.scalar(
            select(func.count(AttestorWarning.id)).where(
                AttestorWarning.attestor_org_id == org_id
            )
        )
        or 0
    )
    late_count = int(
        await db.scalar(
            select(OrgAttestorProfile.late_submission_count).where(
                OrgAttestorProfile.org_id == org_id
            )
        )
        or 0
    )
    penalty = cfg.reliability_penalty * Decimal(warning_count + late_count)
    reliability = FactorResult(
        max(Decimal("0"), Decimal("1") - penalty),
        stood_count,
    )

    return {"rating": rating, "reliability": reliability}
