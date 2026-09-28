"""Add the tables behind the demand map.

Nothing recorded what Operators searched for, so the one question a Contributor
most wants answered — what is missing from the catalogue — had no data behind
it at all. Explore logged neither queries nor results; only `saved_searches`
existed, which is a badly biased sample of people who bothered to save one.

Two tables with deliberately different lifetimes. `search_gaps` holds one row
per zero-result search and carries an identity (a user, or a daily-rotating
HMAC for an anonymous visitor). It is swept after 90 days: identity exists only
to count distinct searchers and to answer an erasure request. `demand_signals`
holds the counts rolled up from those rows, carries no identity at all, and is
never deleted — demand outlives the people who expressed it.

Revision ID: 2026_09_28_0123
Revises: 2026_09_27_0122
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_09_28_0123"
down_revision: str | Sequence[str] | None = "2026_09_27_0122"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the raw search-gap table and the permanent demand rollup."""
    op.create_table(
        "search_gaps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("searcher_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("searcher_key", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "terms",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(searcher_id IS NULL) != (searcher_key IS NULL)",
            name="ck_search_gaps_searcher_xor",
        ),
        sa.ForeignKeyConstraint(["searcher_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_search_gaps_created_at", "search_gaps", ["created_at"])
    op.create_index("idx_search_gaps_searcher_id", "search_gaps", ["searcher_id"])

    op.create_table(
        "demand_signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("term", sa.Text(), server_default="", nullable=False),
        sa.Column("filter_signature", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("searcher_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "period",
            "term",
            "filter_signature",
            name="uq_demand_signals_period_term_filters",
        ),
    )
    op.create_index("idx_demand_signals_period", "demand_signals", ["period"])


def downgrade() -> None:
    """Drop both demand tables."""
    op.drop_index("idx_demand_signals_period", table_name="demand_signals")
    op.drop_table("demand_signals")
    op.drop_index("idx_search_gaps_searcher_id", table_name="search_gaps")
    op.drop_index("idx_search_gaps_created_at", table_name="search_gaps")
    op.drop_table("search_gaps")
