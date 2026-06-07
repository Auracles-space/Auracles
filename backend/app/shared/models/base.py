"""Shared SQLAlchemy model helpers.

Feature modules keep their business tables in module-local `models.py` files,
but common mixins live here so timestamps and typing stay consistent.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class CreatedAtMixin:
    """Add an immutable creation timestamp to a database model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UpdatedAtMixin(CreatedAtMixin):
    """Add creation and update timestamps to a mutable database model."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
