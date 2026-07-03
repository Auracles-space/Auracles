"""Consent service for GDPR legal document acceptance.

Records append-only Terms of Service and Privacy Policy acceptance rows,
loads current legal versions from platform config, and exposes the current
version gate used by privileged routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_address
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.financials.models import PlatformConfig
from app.modules.gdpr.models import ConsentLog
from app.modules.gdpr.schemas import ConsentHistoryResponse, ConsentLogItem

CONSENT_DOCUMENT_CONFIG_KEYS = {
    "terms_of_service": "consent_version_terms_of_service",
    "privacy_policy": "consent_version_privacy_policy",
}
DEFAULT_CONSENT_VERSIONS = {
    "terms_of_service": "1.0",
    "privacy_policy": "1.0",
}


def _normalise_ip(raw_ip: str | None) -> str | None:
    """Return a database-safe IP string or None when the input is unavailable."""
    if raw_ip is None:
        return None
    try:
        return str(ip_address(raw_ip))
    except ValueError:
        return None


async def get_current_consent_versions(db: AsyncSession) -> dict[str, str]:
    """Load current legal document versions from platform config."""
    rows = (
        (
            await db.execute(
                select(PlatformConfig).where(
                    PlatformConfig.key.in_(CONSENT_DOCUMENT_CONFIG_KEYS.values())
                )
            )
        )
        .scalars()
        .all()
    )
    values_by_key = {row.key: row.value for row in rows}
    return {
        document_type: values_by_key.get(config_key, default_version)
        for document_type, config_key in CONSENT_DOCUMENT_CONFIG_KEYS.items()
        for default_version in [DEFAULT_CONSENT_VERSIONS[document_type]]
    }


async def get_missing_current_consents(
    db: AsyncSession,
    user_id: UUID,
) -> list[str]:
    """Return legal documents where the user lacks the current version."""
    current_versions = await get_current_consent_versions(db)
    rows = (
        await db.execute(
            select(ConsentLog.document_type, ConsentLog.version).where(
                ConsentLog.user_id == user_id
            )
        )
    ).all()
    accepted_versions = {(document_type, version) for document_type, version in rows}
    return [
        document_type
        for document_type, current_version in current_versions.items()
        if (document_type, current_version) not in accepted_versions
    ]


async def record_current_consents(
    db: AsyncSession,
    user_id: UUID,
    ip: str | None = None,
    ua: str | None = None,
) -> list[ConsentLog]:
    """Append consent rows for all current legal document versions."""
    current_versions = await get_current_consent_versions(db)
    accepted_at = datetime.now(UTC)
    rows: list[ConsentLog] = []
    for document_type, version in current_versions.items():
        row = ConsentLog(
            user_id=user_id,
            document_type=document_type,
            version=version,
            accepted_at=accepted_at,
            ip=_normalise_ip(ip),
            user_agent=ua,
        )
        db.add(row)
        rows.append(row)
        await write_audit(
            db=db,
            actor_id=user_id,
            action="consent_recorded",
            target_type="consent_log",
            metadata={"document_type": document_type, "version": version},
            ip=ip,
            ua=ua,
        )
    await db.flush()
    return rows


async def get_consent_history(
    db: AsyncSession,
    user_id: UUID,
) -> ConsentHistoryResponse:
    """Return current consent status and append-only acceptance history."""
    current_versions = await get_current_consent_versions(db)
    missing_documents = await get_missing_current_consents(db, user_id)
    rows = (
        (
            await db.execute(
                select(ConsentLog)
                .where(ConsentLog.user_id == user_id)
                .order_by(desc(ConsentLog.accepted_at))
            )
        )
        .scalars()
        .all()
    )
    return ConsentHistoryResponse(
        current_versions=current_versions,
        missing_documents=missing_documents,
        items=[
            ConsentLogItem(
                id=row.id,
                document_type=row.document_type,
                version=row.version,
                accepted_at=row.accepted_at,
            )
            for row in rows
        ],
    )
