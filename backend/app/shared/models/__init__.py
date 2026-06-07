"""Shared model exports.

Importing this package registers shared tables with SQLAlchemy metadata for
Alembic autogeneration and later feature modules.
"""

from app.shared.models.audit_log import AuditLog
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

__all__ = ["AuditLog", "CreatedAtMixin", "UpdatedAtMixin"]
