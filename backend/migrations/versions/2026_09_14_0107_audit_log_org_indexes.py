"""Index audit logs by target and by the org id carried in metadata.

The admin organization detail audit view (Decision 1 of the organizations
end-to-end design) reads rows whose ``target_id`` is the organization or
whose ``metadata->>'org_id'`` names it. Neither had an index, so each page
scanned the whole table. Both indexes are built concurrently so a deploy
never blocks audit writes while they build.

Revision ID: 2026_09_14_0107
Revises: 2026_09_14_0106
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_09_14_0107"
down_revision: str | Sequence[str] | None = "2026_09_14_0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_INDEX = "ix_audit_logs_target_id_created_at"
ORG_ID_INDEX = "ix_audit_logs_metadata_org_id"


def upgrade() -> None:
    """Create the target and metadata org id indexes concurrently."""
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {TARGET_INDEX} "
            "ON audit_logs (target_id, created_at)"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {ORG_ID_INDEX} "
            "ON audit_logs ((metadata->>'org_id'))"
        )


def downgrade() -> None:
    """Drop both indexes concurrently."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_audit_logs_metadata_org_id")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_audit_logs_target_id_created_at"
        )
