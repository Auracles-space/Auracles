"""Index Projects for full-text search on the Contributor feed.

The open marketplace feed gained a search box, so every keystroke matches a
tsquery against ``title || ' ' || description``. Without an index that is a
sequential scan of every Project on the platform per request, on a feed that is
polled as the user types.

The expression below must stay textually identical to
``_PROJECT_SEARCH_DOCUMENT`` in app/modules/projects/service.py. Postgres only
uses an expression index when the query's expression matches it exactly, and a
mismatch does not error — it silently falls back to the scan this exists to
prevent. Both columns are NOT NULL, so no COALESCE is needed; adding one here
without adding it there would be exactly that silent mismatch.

Maps to: FR-PROJ-002 (open Project marketplace view).

Revision ID: 2026_10_15_0128
Revises: 2026_10_14_0127
Create Date: 2026-10-15
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2026_10_15_0128"
down_revision: str | Sequence[str] | None = "2026_10_14_0127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_projects_search_document"


def upgrade() -> None:
    """Add the GIN index backing Project search."""
    op.execute(
        f"CREATE INDEX {_INDEX_NAME} ON projects USING gin "
        "(to_tsvector('english', projects.title || ' ' || projects.description))"
    )


def downgrade() -> None:
    """Drop the Project search index."""
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
