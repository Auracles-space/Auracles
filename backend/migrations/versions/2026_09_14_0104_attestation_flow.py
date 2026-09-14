"""Offer decline reasons; requestor-facing attestation notification labels.

Slice 3 of the organizations + attestation rework (docs/superpowers/specs/
2026-09-14-attestation-request-to-report-design.md). An attestor org could
decline an offer with no reason, so admins saw repeated declines and nothing
else. The reason now lives on the offer. Two notification labels are added
for events the requestor and attestor orgs were never told about: a request
withdrawn while an org held an open offer, and a clarification that lapsed.

Revision ID: 2026_09_14_0104
Revises: 2026_09_13_0103
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_14_0104"
down_revision: str | Sequence[str] | None = "2026_09_13_0103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_LABELS: tuple[str, ...] = (
    "attestation_withdrawn",
    "attestation_clarification_expired",
)


def upgrade() -> None:
    """Add the decline reason column and the new notification labels."""
    op.add_column(
        "attestation_offers",
        sa.Column("decline_reason", sa.Text(), nullable=True),
    )
    for label in NEW_LABELS:
        op.execute(
            f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{label}'"
        )


def downgrade() -> None:
    """Drop the column and purge rows under the new labels.

    Postgres cannot remove enum values, so the labels stay; rows using them
    are deleted so a later re-add never collides.
    """
    labels = ", ".join(f"'{label}'" for label in NEW_LABELS)
    op.execute(f"DELETE FROM notifications WHERE type::text IN ({labels})")
    op.drop_column("attestation_offers", "decline_reason")
