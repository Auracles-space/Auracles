"""Organization slug history and the ``org_slug_changed`` notification label.

Decision 5 of the organizations end-to-end design (docs/superpowers/specs/
2026-09-14-organizations-end-to-end-design.md §Slug change): owners may change
their organization's slug. Every previous slug is kept here so ``/orgs/{old}``
keeps resolving to the organization and nobody else can claim an old slug to
impersonate it. The unique constraint on ``slug`` is what reserves it
platform-wide; the notification label tells the other owners the public
address moved.

Revision ID: 2026_09_14_0106
Revises: 2026_09_14_0105
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "2026_09_14_0106"
down_revision: str | Sequence[str] | None = "2026_09_14_0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_LABEL = "org_slug_changed"


def upgrade() -> None:
    """Create ``org_slug_history`` and add the notification label."""
    op.create_table(
        "org_slug_history",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("slug", name="uq_org_slug_history_slug"),
    )
    op.create_index("idx_org_slug_history_org", "org_slug_history", ["org_id"])
    op.execute(
        f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{NEW_LABEL}'"
    )


def downgrade() -> None:
    """Purge rows under the label Postgres cannot drop, then drop the table."""
    op.execute(f"DELETE FROM notifications WHERE type::text = '{NEW_LABEL}'")
    op.drop_index("idx_org_slug_history_org", table_name="org_slug_history")
    op.drop_table("org_slug_history")
