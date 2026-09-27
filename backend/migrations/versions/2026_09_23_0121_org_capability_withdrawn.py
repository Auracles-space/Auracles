"""Add the `withdrawn` org capability status for owner-initiated wind-down.

An organization owner could not close their own organization. The close
refuses while any capability is `active`, and every capability status change
was admin-only (`admin_set_*`). Account deletion then refuses while you are
the sole owner of an org with an active capability — so an owner who wanted
out had no route that did not go through support.

`withdrawn` is the state an owner puts a capability into themselves. It is a
new label rather than a reuse of `revoked` because `revoked` means an admin
took the capability away: it bars re-application via
`_CAPABILITY_REAPPLY_REFUSALS`, and the owner-facing copy tells them to
appeal. Neither is true of a decision they made.

Safe by construction: every capability gate in the codebase tests
`status == "active"`, so a new non-active label blocks exactly like `revoked`.

Revision ID: 2026_09_23_0121
Revises: 2026_09_19_0120
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_23_0121"
down_revision: str | Sequence[str] | None = "2026_09_19_0120"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add `withdrawn` to the org capability status enum."""
    op.execute(
        "ALTER TYPE org_capability_status_enum ADD VALUE IF NOT EXISTS 'withdrawn'"
    )


def downgrade() -> None:
    """Move withdrawn capabilities to revoked.

    Postgres cannot drop an enum label, so the job here is to leave no row
    holding a value the older code does not understand. `revoked` is the
    nearest non-active state: the capability stays blocked either way, and
    only the reason it is blocked is lost.
    """
    op.execute(
        "UPDATE org_capabilities SET status = 'revoked' WHERE status = 'withdrawn'"
    )
