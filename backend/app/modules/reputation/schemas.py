"""Public reputation read schemas (Phase 5e).

Exposes the headline 0-100 score, the provisional flag, and named contributing
factors with a relative-strength label only — never the raw weights or
normalized sub-values (full-spec section 3234, anti-gaming).

Maps to: BR-ATT-005.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReputationFactorLabel(BaseModel):
    """One contributing factor and its public strength label."""

    factor: str
    label: str  # strong | moderate | weak


class ReputationSummary(BaseModel):
    """Compact reputation badge embedded in other responses (cards, profiles).

    Numeric ``score`` is suppressed while ``is_provisional`` so low-evidence
    subjects render as "New" rather than a misleading number.
    """

    score: Decimal | None = None
    is_provisional: bool = True
    factors: list[ReputationFactorLabel] = Field(default_factory=list)


class ReputationResponse(BaseModel):
    """Public reputation payload for one subject."""

    model_config = ConfigDict(from_attributes=True)

    subject_type: str
    subject_id: UUID
    score: Decimal | None
    is_provisional: bool
    factors: list[ReputationFactorLabel]
    last_calculated_at: datetime | None
