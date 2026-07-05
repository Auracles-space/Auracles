"""Reputation compute engine + persistence + reads.

Combines per-subject factor results into a 0-100 score with shrinkage toward a
neutral prior, provisional gating for low-evidence subjects, and an upsert into
``reputation_scores``. See the Phase 5e design spec.

Maps to: BR-ATT-005, BR-FWK-005.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reputation.models import ReputationScore
from app.modules.reputation.weights import ReputationConfig, load_config

VALID_SUBJECT_TYPES = (
    "framework",
    "contributor",
    "operator",
    "attestor",
    "attestor_org",
)

_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


@dataclass(frozen=True)
class FactorResult:
    """One normalized factor contribution and its supporting evidence count."""

    value: Decimal  # normalized 0..1
    evidence: int  # evidence count contributing to this factor


@dataclass(frozen=True)
class ScoreResult:
    """Combined reputation outcome for one subject."""

    score: Decimal  # 0..100, two decimals
    components: dict[str, Any]
    is_provisional: bool
    evidence: int


def _clamp(value: Decimal) -> Decimal:
    """Clamp a normalized value into the closed unit interval."""
    return min(Decimal("1"), max(Decimal("0"), value))


def _label(value: Decimal) -> str:
    """Map a normalized value to a public strength label."""
    if value >= Decimal("0.66"):
        return "strong"
    if value >= Decimal("0.33"):
        return "moderate"
    return "weak"


def _component(fr: FactorResult) -> dict[str, str]:
    """Render one factor's public component payload (clamped value + label)."""
    clamped = _clamp(fr.value)
    return {"value": str(clamped.quantize(_FOUR)), "label": _label(clamped)}


def combine_factors(
    cfg: ReputationConfig,
    factors: dict[str, FactorResult],
) -> ScoreResult:
    """Weight, shrink toward prior, and label factor results into a ScoreResult.

    Args:
        cfg: Loaded reputation config for the subject type (weights, prior, k,
            min-activity threshold).
        factors: Mapping of factor name to its normalized result.

    Returns:
        A ScoreResult with a 0-100 score, public component labels, the
        provisional flag, and total evidence volume.
    """
    raw = Decimal("0")
    for name, weight in cfg.weights.items():
        fr = factors.get(name, FactorResult(Decimal("0"), 0))
        raw += weight * _clamp(fr.value)

    total_evidence = sum(fr.evidence for fr in factors.values())
    n = Decimal(total_evidence)
    k = cfg.prior_strength_k
    denom = n + k
    # denom == 0 only when both evidence and prior strength are zero.
    shrunk = raw if denom == 0 else (n / denom) * raw + (k / denom) * cfg.prior
    score = (shrunk * Decimal("100")).quantize(_TWO, rounding=ROUND_HALF_UP)

    components = {
        name: _component(factors.get(name, FactorResult(Decimal("0"), 0)))
        for name in cfg.weights
    }
    is_provisional = total_evidence < cfg.min_activity
    return ScoreResult(score, components, is_provisional, total_evidence)


async def upsert_score(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: UUID,
    result: ScoreResult,
) -> None:
    """Idempotently upsert one computed score row."""
    now = datetime.now(UTC)
    stmt = (
        pg_insert(ReputationScore)
        .values(
            subject_type=subject_type,
            subject_id=subject_id,
            score=result.score,
            components=result.components,
            is_provisional=result.is_provisional,
            last_calculated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_reputation_subject",
            set_={
                "score": result.score,
                "components": result.components,
                "is_provisional": result.is_provisional,
                "last_calculated_at": now,
                "updated_at": now,
            },
        )
    )
    await db.execute(stmt)


async def get_score(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: UUID,
) -> ReputationScore | None:
    """Return the latest stored reputation score for one subject, if any."""
    return cast(
        "ReputationScore | None",
        await db.scalar(
            select(ReputationScore).where(
                ReputationScore.subject_type == subject_type,
                ReputationScore.subject_id == subject_id,
            )
        ),
    )


async def subject_exists(
    db: AsyncSession, *, subject_type: str, subject_id: UUID
) -> bool:
    """Return whether the scored subject exists for recompute/admin flows.

    This check is intentionally broader than public visibility. It validates the
    subject's type contract (framework vs contributor vs operator) without
    applying marketplace-public filters such as published status or suspension.
    """
    from app.modules.attestation.models import AttestorProfile
    from app.modules.auth.models import UserRole
    from app.modules.frameworks.models import Framework
    from app.modules.organizations.models import OrgAttestorProfile

    if subject_type == "framework":
        return (
            await db.scalar(select(Framework.id).where(Framework.id == subject_id))
            is not None
        )
    if subject_type == "attestor":
        return (
            await db.scalar(
                select(AttestorProfile.id).where(AttestorProfile.user_id == subject_id)
            )
            is not None
        )
    if subject_type == "attestor_org":
        return (
            await db.scalar(
                select(OrgAttestorProfile.id).where(
                    OrgAttestorProfile.org_id == subject_id
                )
            )
            is not None
        )
    role = "contributor" if subject_type == "contributor" else "operator"
    return (
        await db.scalar(
            select(UserRole.id).where(
                UserRole.user_id == subject_id,
                UserRole.role == role,
            )
        )
        is not None
    )


async def _public_subject_exists(
    db: AsyncSession, *, subject_type: str, subject_id: UUID
) -> bool:
    """Return whether a reputation subject is visible on public read routes."""
    from app.modules.attestation.models import AttestorProfile
    from app.modules.auth.models import User, UserRole
    from app.modules.frameworks.models import Framework
    from app.modules.organizations.models import Organization, OrgAttestorProfile

    if subject_type == "framework":
        return (
            await db.scalar(
                select(Framework.id)
                .join(User, User.id == Framework.contributor_id)
                .where(
                    Framework.id == subject_id,
                    Framework.status == "published",
                    User.suspended_at.is_(None),
                )
            )
            is not None
        )

    if subject_type == "contributor":
        contributor = await db.scalar(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                User.id == subject_id,
                UserRole.role == "contributor",
                User.suspended_at.is_(None),
            )
        )
        if contributor is None:
            return False
        return (
            await db.scalar(
                select(Framework.id).where(
                    Framework.contributor_id == subject_id,
                    Framework.status == "published",
                )
            )
            is not None
        )

    if subject_type == "attestor":
        return (
            await db.scalar(
                select(AttestorProfile.id).where(
                    AttestorProfile.user_id == subject_id,
                    AttestorProfile.active.is_(True),
                )
            )
            is not None
        )

    if subject_type == "attestor_org":
        return (
            await db.scalar(
                select(OrgAttestorProfile.id)
                .join(Organization, Organization.id == OrgAttestorProfile.org_id)
                .where(
                    OrgAttestorProfile.org_id == subject_id,
                    OrgAttestorProfile.active.is_(True),
                    Organization.suspended_at.is_(None),
                    Organization.deactivated_at.is_(None),
                )
            )
            is not None
        )

    return await subject_exists(db, subject_type=subject_type, subject_id=subject_id)


def _public_factors(
    cfg: ReputationConfig, score: ReputationScore | None
) -> list[dict[str, str]]:
    """Project stored components onto public {factor, label} entries.

    Only factors with a positive weight are surfaced; zero-weight launch
    placeholders (e.g. completion/recency) stay internal. Sub-values and
    weights are never exposed.
    """
    if score is None or not score.components:
        return []
    out: list[dict[str, str]] = []
    for name, weight in cfg.weights.items():
        if weight <= 0:
            continue
        component = score.components.get(name)
        if not component or "label" not in component:
            continue
        out.append({"factor": name, "label": component["label"]})
    return out


async def read_reputation(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: UUID,
    public: bool = False,
) -> dict[str, Any] | None:
    """Build the public reputation payload for one subject.

    Returns ``None`` when the subject does not exist (router maps to 404). A
    subject that exists but was never scored reads as provisional with an empty
    factor list ("New").

    Args:
        db: Async session.
        subject_type: One of ``framework``, ``contributor``, ``operator``,
            ``attestor``.
        subject_id: UUID of the subject.
        public: When true, enforce public-surface visibility rules instead of
            broad recompute/admin existence checks.

    Returns:
        A mapping suitable for ``ReputationResponse``, or ``None`` if missing.
    """
    exists = (
        await _public_subject_exists(
            db, subject_type=subject_type, subject_id=subject_id
        )
        if public
        else await subject_exists(db, subject_type=subject_type, subject_id=subject_id)
    )
    if not exists:
        return None
    score = await get_score(db, subject_type=subject_type, subject_id=subject_id)
    cfg = await load_config(db, subject_type=subject_type)
    provisional = score.is_provisional if score is not None else True
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "score": None if (score is None or provisional) else score.score,
        "is_provisional": provisional,
        "factors": _public_factors(cfg, score),
        "last_calculated_at": (score.last_calculated_at if score is not None else None),
    }


def summary_payload(
    cfg: ReputationConfig, score: ReputationScore | None
) -> dict[str, Any]:
    """Build an embeddable reputation summary; hide the number while provisional."""
    provisional = score.is_provisional if score is not None else True
    return {
        "score": None if (score is None or provisional) else score.score,
        "is_provisional": provisional,
        "factors": _public_factors(cfg, score),
    }


async def summaries_for_subjects(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    """Batch-load embeddable reputation summaries keyed by subject id.

    Subjects without a stored score still receive a provisional "New" summary so
    embedded surfaces can render the cold-start badge before the first daily
    recompute.
    """
    if not subject_ids:
        return {}
    cfg = await load_config(db, subject_type=subject_type)
    rows = (
        (
            await db.execute(
                select(ReputationScore).where(
                    ReputationScore.subject_type == subject_type,
                    ReputationScore.subject_id.in_(subject_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    row_map = {row.subject_id: row for row in rows}
    return {
        subject_id: summary_payload(cfg, row_map.get(subject_id))
        for subject_id in subject_ids
    }


async def operator_reputation_visible(
    db: AsyncSession,
    *,
    operator_id: UUID,
    requester_id: UUID,
    requester_roles: list[str],
) -> bool:
    """Return whether ``requester`` may read ``operator``'s reputation.

    Visible to the operator themselves, to any admin, and to a contributor who
    is in a deal with the operator — i.e. holds a pending or accepted Proposal
    on one of that operator's Projects (BR-ATT-005, contextual visibility).
    """
    from app.modules.projects.models import Project, Proposal

    if requester_id == operator_id or "admin" in requester_roles:
        return True
    in_deal = await db.scalar(
        select(Proposal.id)
        .join(Project, Project.id == Proposal.project_id)
        .where(
            Project.operator_id == operator_id,
            Proposal.contributor_id == requester_id,
            Proposal.status.in_(("pending", "accepted")),
        )
        .limit(1)
    )
    return in_deal is not None
