"""Database-backed security audit helper.

Loguru remains the operational log stream. This helper writes queryable audit
events to PostgreSQL for user-visible settings, admin review, and compliance
workflows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models.audit_log import AuditLog


async def write_audit(
    db: AsyncSession,
    actor_id: UUID | None,
    action: str,
    target_type: str = "system",
    target_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> AuditLog:
    """Persist a security event without committing the caller's transaction."""
    audit_log = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_=metadata or {},
        ip_address=ip,
        user_agent=ua,
    )
    db.add(audit_log)
    await db.flush()
    return audit_log
