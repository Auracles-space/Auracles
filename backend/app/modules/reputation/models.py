"""SQLAlchemy models for reputation scoring state.

Stores one upserted score row per subject so public and contextual read paths
can serve the latest computed reputation without recalculating on request.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import UpdatedAtMixin


class ReputationScore(UpdatedAtMixin, Base):
    """Latest computed reputation snapshot for one subject."""

    __tablename__ = "reputation_scores"
    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", name="uq_reputation_subject"),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_reputation_score_range",
        ),
        CheckConstraint(
            "subject_type IN ('framework','contributor','operator')",
            name="ck_reputation_subject_type",
        ),
        Index("ix_reputation_subject_type_score", "subject_type", "score"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    components: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    is_provisional: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text("true"),
    )
    last_calculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
