"""Seeded review rubrics for the Attestation Review Workspace.

Rubrics are durable compliance artifacts: published reports must reproduce the
exact rubric version used at submission time. These constants are the source
for the migration seed, quality gate, and report rendering layers.

Maps to: design spec section 3.4 and workflow section 4.2/4.6(c).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

RUBRIC_VERSION: int = 1


@dataclass(frozen=True)
class RubricDimension:
    """One scored dimension within a review-type rubric."""

    key: str
    label: str
    weight: Decimal
    display_order: int


def _dims(rows: list[tuple[str, str, str]]) -> list[RubricDimension]:
    """Build ordered rubric dimensions from key/label/weight tuples."""
    return [
        RubricDimension(
            key=key,
            label=label,
            weight=Decimal(weight),
            display_order=display_order,
        )
        for display_order, (key, label, weight) in enumerate(rows)
    ]


RUBRICS: dict[str, list[RubricDimension]] = {
    "quality": _dims(
        [
            ("completeness", "Completeness", "0.18"),
            ("implementability", "Implementability", "0.18"),
            ("accuracy", "Accuracy", "0.18"),
            ("clarity", "Clarity", "0.12"),
            ("version_currency", "Version Currency", "0.10"),
            ("appropriate_scope", "Appropriate Scope", "0.10"),
            ("risk_flags", "Risk Flags", "0.08"),
            ("recommended_use_cases", "Recommended Use Cases", "0.06"),
        ]
    ),
    "compliance": _dims(
        [
            ("regulatory_alignment", "Regulatory Alignment", "0.25"),
            ("jurisdictional_coverage", "Jurisdictional Coverage", "0.20"),
            ("control_adequacy", "Control Adequacy", "0.20"),
            ("evidence_traceability", "Evidence Traceability", "0.15"),
            ("gap_identification", "Gap Identification", "0.12"),
            ("update_currency", "Update Currency", "0.08"),
        ]
    ),
    "expert": _dims(
        [
            ("technical_soundness", "Technical Soundness", "0.25"),
            ("methodological_rigor", "Methodological Rigor", "0.20"),
            ("domain_accuracy", "Domain Accuracy", "0.20"),
            ("practical_applicability", "Practical Applicability", "0.15"),
            ("innovation_value", "Innovation Value", "0.10"),
            ("limitations_disclosure", "Limitations Disclosure", "0.10"),
        ]
    ),
    "provenance": _dims(
        [
            ("authorship_verification", "Authorship Verification", "0.30"),
            ("source_integrity", "Source Integrity", "0.25"),
            ("originality", "Originality", "0.20"),
            ("chain_of_custody", "Chain of Custody", "0.15"),
            ("attribution_completeness", "Attribution Completeness", "0.10"),
        ]
    ),
}

METHODOLOGY: dict[str, str] = {
    "quality": (
        "This review assessed completeness, implementability, accuracy, clarity, "
        "version currency, scope, risk flags, and recommended use cases. Each "
        "dimension was scored 1-5 and weighted into the overall determination."
    ),
    "compliance": (
        "This review assessed regulatory alignment, jurisdictional coverage, "
        "control adequacy, evidence traceability, gap identification, and "
        "update currency against the applicable compliance baseline."
    ),
    "expert": (
        "This review applied domain expert judgment across technical soundness, "
        "methodological rigor, domain accuracy, practical applicability, "
        "innovation value, and disclosure of limitations."
    ),
    "provenance": (
        "This review verified authorship, source integrity, originality, chain "
        "of custody, and attribution completeness of the submitted materials."
    ),
}


def weighted_overall(scores: dict[str, int], review_type: str) -> Decimal:
    """Compute the weighted overall rubric score for one review type.

    Args:
        scores: Mapping of rubric dimension keys to integer scores from 1 to 5.
        review_type: Review type key selecting one seeded rubric.

    Returns:
        The weighted overall score, quantized to two decimal places.

    Raises:
        ValueError: If the review type is unknown, a dimension is missing, or a
            score falls outside the 1-5 range.
    """
    dimensions = RUBRICS.get(review_type)
    if dimensions is None:
        raise ValueError(f"Unknown review_type: {review_type}")

    total = Decimal("0")
    for dimension in dimensions:
        if dimension.key not in scores:
            raise ValueError(f"Missing score for dimension: {dimension.key}")
        score = scores[dimension.key]
        if not 1 <= score <= 5:
            raise ValueError(
                f"Score out of range for {dimension.key}: {score}"
            )
        total += dimension.weight * Decimal(score)

    return total.quantize(Decimal("0.01"))
