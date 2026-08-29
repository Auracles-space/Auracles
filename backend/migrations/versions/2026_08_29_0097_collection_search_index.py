"""Add the full-text search index Collections were missing.

Explore searches Frameworks and Collections into one mixed catalog, but only
`frameworks` had a text-search index — and nothing queried it, because the
service matched with `ILIKE '%q%'`, whose leading wildcard no index can serve.
Now that both sides match with `to_tsvector @@ tsquery`, Collections needs the
equivalent index or its half of the catalog stays a sequential scan.

The expression here must stay textually identical to the one in
`app/modules/explore/service.py::_COLLECTION_SEARCH_DOCUMENT`: Postgres only
uses an expression index when the query expression matches the indexed one node
for node. `title` and `description` are both NOT NULL, so the concatenation
cannot evaluate to NULL and leave rows unindexed.

Maps to: FR-EXP-001 (marketplace search), CLAUDE.md locked decision
"Search (MVP): Postgres full-text search (GIN index)".

Revision ID: 2026_08_29_0097
Revises: 2026_08_28_0096
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_08_29_0097"
down_revision: str | Sequence[str] | None = "2026_08_28_0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Collections full-text GIN index."""
    op.execute(
        """
        CREATE INDEX idx_framework_collections_search
        ON framework_collections
        USING gin (
            to_tsvector(
                'english',
                title || ' ' || description
            )
        )
        """
    )


def downgrade() -> None:
    """Drop the Collections full-text GIN index."""
    op.execute("DROP INDEX IF EXISTS idx_framework_collections_search")
