"""Attestation submission quality gate for Module 4 review workspaces.

The gate runs inline before report submission commits any state change. It
returns every unmet requirement at once so the assigned Attestor can fix the
workspace in a single pass.

Maps to: design spec section 4.7.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    Attestation,
    AttestationAnnotation,
    AttestationClarification,
    AttestationRubricDimension,
    AttestationRubricScore,
)
from app.modules.financials.models import PlatformConfig

DEFAULT_MIN_WORDS = 150
_CONTACT_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)"),
)


async def _platform_int_config(
    db: AsyncSession,
    *,
    key: str,
    default: int,
) -> int:
    """Return one integer PlatformConfig value or the provided default."""
    raw = await db.scalar(select(PlatformConfig.value).where(PlatformConfig.key == key))
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


async def _contact_check_enabled(db: AsyncSession) -> bool:
    """Return whether contact-leak blocking is enabled for report text."""
    raw = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "attestation_report_block_contact_info"
        )
    )
    return raw != "0"


async def evaluate_quality_gate(
    db: AsyncSession,
    *,
    attestation: Attestation,
    summary: str,
    scope: str,
    conditions: str | None,
    outcome: str,
) -> list[str]:
    """Return the list of quality-gate failures for one attestation draft.

    Args:
        db: Async database session.
        attestation: In-review attestation being submitted.
        summary: Proposed report executive summary text.
        scope: Proposed scope-of-review text.
        conditions: Optional conditions text for conditional outcomes.
        outcome: Proposed overall determination.

    Returns:
        A list of human-readable failures. An empty list means the submission
        satisfies the gate.
    """
    dimensions = (
        (
            await db.execute(
                select(AttestationRubricDimension).where(
                    AttestationRubricDimension.review_type == attestation.review_type,
                    AttestationRubricDimension.version == rubrics.RUBRIC_VERSION,
                )
            )
        )
        .scalars()
        .all()
    )
    score_rows = (
        (
            await db.execute(
                select(AttestationRubricScore).where(
                    AttestationRubricScore.attestation_id == attestation.id
                )
            )
        )
        .scalars()
        .all()
    )
    scores_by_dimension = {row.dimension_id: row for row in score_rows}
    failures: list[str] = []
    comment_word_count = 0

    for dimension in dimensions:
        row = scores_by_dimension.get(dimension.id)
        comment_text = (row.comment or "") if row is not None else ""
        if row is None or row.score is None or not comment_text.strip():
            failures.append(
                f"Rubric dimension '{dimension.label}' needs a score and comment."
            )
            continue
        comment_word_count += len(comment_text.split())

    stripped_conditions = (conditions or "").strip()
    if outcome == "conditional" and not stripped_conditions:
        failures.append("A conditional outcome requires conditions text.")
    if outcome != "conditional" and stripped_conditions:
        failures.append("Conditions text is only allowed for conditional outcomes.")

    annotation_count = await db.scalar(
        select(func.count())
        .select_from(AttestationAnnotation)
        .where(AttestationAnnotation.attestation_id == attestation.id)
    )
    if outcome in {"conditional", "rejected"} and not annotation_count:
        failures.append("A non-approved outcome requires at least one annotation.")

    min_words = await _platform_int_config(
        db,
        key="attestation_report_min_words",
        default=DEFAULT_MIN_WORDS,
    )
    total_words = (
        comment_word_count + len(summary.split()) + len(stripped_conditions.split())
    )
    if total_words < min_words:
        failures.append(
            f"Report is too short: {total_words} words (minimum {min_words})."
        )

    if await _contact_check_enabled(db):
        content_blob = " ".join(
            [summary, scope, stripped_conditions]
            + [row.comment or "" for row in score_rows]
        )
        if any(pattern.search(content_blob) for pattern in _CONTACT_PATTERNS):
            failures.append(
                "Report contains contact information; communicate via the platform."
            )

    open_clarifications = await db.scalar(
        select(func.count())
        .select_from(AttestationClarification)
        .where(
            AttestationClarification.attestation_id == attestation.id,
            AttestationClarification.status == "open",
        )
    )
    if open_clarifications:
        failures.append("Resolve the open clarification before submitting.")

    return failures
