"""Shared test cleanup helpers for identity-linked rows.

Many backend tests create Users plus security-adjacent rows such as audit logs
and KYC documents. These helpers delete the FK blockers before user cleanup so
fixtures remain order-independent across the full suite.
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.auth.models import (
    IdentityVerification,
    KycDocument,
    User,
    UserRole,
)
from app.modules.notifications.models import (
    Notification,
    NotificationDeliveryMarker,
)
from app.shared.models.audit_log import AuditLog


async def clear_identity_state_async(session: AsyncSession) -> None:
    """Delete notification, audit, KYC, role, and user rows in FK-safe order."""
    await session.execute(delete(NotificationDeliveryMarker))
    await session.execute(delete(Notification))
    await session.execute(delete(AuditLog))
    await session.execute(delete(IdentityVerification))
    await session.execute(delete(KycDocument))
    await session.execute(delete(UserRole))
    await session.execute(delete(User))


def clear_identity_state_sync(session: Session) -> None:
    """Delete notification, audit, KYC, role, and user rows in FK-safe order."""
    session.execute(delete(NotificationDeliveryMarker))
    session.execute(delete(Notification))
    session.execute(delete(AuditLog))
    session.execute(delete(IdentityVerification))
    session.execute(delete(KycDocument))
    session.execute(delete(UserRole))
    session.execute(delete(User))
