"""SQLAlchemy model for the pre-launch marketing waitlist.

Stores one row per unique, normalized email collected from the public landing
page. The unique constraint on `email` is the single source of deduplication.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin


class WaitlistEntry(CreatedAtMixin, Base):
    """A single pre-launch waitlist signup keyed by normalized email."""

    __tablename__ = "waitlist_entries"
    __table_args__ = (
        UniqueConstraint("email", name="uq_waitlist_entries_email"),
        Index("idx_waitlist_entries_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Free-form origin hint (e.g. "hero", "footer") for later funnel analysis.
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
