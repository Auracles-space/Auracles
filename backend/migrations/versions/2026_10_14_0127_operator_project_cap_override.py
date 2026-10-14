"""Give one Operator account its own active-Project ceiling.

BR-PROJ-004 caps an Operator at five concurrent active Projects, and the number
lived only as a module constant. Lifting it for a single account therefore meant
amending the rule for every Operator in production — the cap is there to bound
escrow exposure, so that is not a trade anyone wanted to make for one person.

``users.max_active_projects`` is that account's ceiling. NULL is the normal
state and means "use BR-PROJ-004's default", deliberately distinct from a
number: a nullable column keeps the business rule in one place rather than
stamping five onto every row and losing the ability to change it.

Nothing is backfilled and nothing is deleted. The organization branch of the
cap is untouched and still reads the constant.

Revision ID: 2026_10_14_0127
Revises: 2026_10_04_0126
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_10_14_0127"
down_revision: str | None = "2026_10_04_0126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable per-account ceiling with a floor of one."""
    op.add_column(
        "users",
        sa.Column("max_active_projects", sa.Integer(), nullable=True),
    )
    # A zero or negative ceiling would silently bar the account from posting at
    # all, which is a suspension wearing the wrong name. Removing the override
    # is expressed as NULL, not as zero.
    op.create_check_constraint(
        "ck_users_max_active_projects_positive",
        "users",
        "max_active_projects IS NULL OR max_active_projects >= 1",
    )


def downgrade() -> None:
    """Drop the override, returning every account to the default ceiling.

    An account currently over the default keeps its existing Projects — the cap
    is enforced on create, not on read — but cannot post another until it comes
    back under five.
    """
    op.drop_constraint(
        "ck_users_max_active_projects_positive",
        "users",
        type_="check",
    )
    op.drop_column("users", "max_active_projects")
