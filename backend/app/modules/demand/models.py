"""Demand models: raw search gaps and the permanent counts rolled up from them.

A search that returns no results is the one search worth keeping — it is a gap
in the catalogue, stated by someone who wanted something we did not have.

Two tables with deliberately different lifetimes. `search_gaps` carries an
identity (a user, or a rotating key for an anonymous visitor) and is deleted
after 90 days: identity exists only to count distinct searchers and to honour a
deletion request. `demand_signals` holds the counts those rows produced, has no
identity at all, and is never deleted — demand outlives the people who
expressed it.

Maps to: FR-SRCH (search), FR-GDPR (retention and erasure).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SearchGap(Base):
    """One Explore search that returned no results.

    Exactly one of ``searcher_id`` and ``searcher_key`` is set: a signed-in
    Operator is attributable and so reachable by a GDPR export or deletion, and
    an anonymous visitor carries only a daily-rotating HMAC that stops being
    linkable to anyone once the salt is discarded.
    """

    __tablename__ = "search_gaps"
    __table_args__ = (
        CheckConstraint(
            "(searcher_id IS NULL) != (searcher_key IS NULL)",
            name="ck_search_gaps_searcher_xor",
        ),
        # The retention sweep deletes by age; the rollup reads by month.
        Index("idx_search_gaps_created_at", "created_at"),
        Index("idx_search_gaps_searcher_id", "searcher_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    searcher_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    searcher_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    terms: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DemandSignal(Base):
    """Distinct-searcher counts for one term or filter combination in one month.

    Carries no identity, so it is neither exported nor erased — there is no
    person in it. This is what the public demand map reads.
    """

    __tablename__ = "demand_signals"
    __table_args__ = (
        # `term` and `filter_signature` are empty strings rather than NULL so
        # the uniqueness actually binds: Postgres treats NULLs as distinct.
        UniqueConstraint(
            "period",
            "term",
            "filter_signature",
            name="uq_demand_signals_period_term_filters",
        ),
        Index("idx_demand_signals_period", "period"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)
    term: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    filter_signature: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="",
    )
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    searcher_count: Mapped[int] = mapped_column(Integer, nullable=False)
