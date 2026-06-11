"""Developer API key lifecycle service.

Handles raw-once API key generation, SHA-256 persistence, metadata listing,
label updates, and revocation. The raw key is never stored and is only returned
from `create_api_key`.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.developer.constants import VALID_API_KEY_SCOPES
from app.modules.developer.models import ApiKey, DeveloperAccount
from app.modules.developer.schemas import (
    ApiKeyCreateRequest,
    ApiKeyUpdateRequest,
)

API_KEY_PREFIX = "ak_"
API_KEY_RANDOM_BYTES = 32
API_KEY_PREFIX_LENGTH = 12
def _hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest stored for API key lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _generate_raw_api_key() -> str:
    """Generate a high-entropy partner API key with a recognizable prefix."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(API_KEY_RANDOM_BYTES)}"


def _validate_scopes(scopes: list[str]) -> list[str]:
    """Return de-duplicated scopes or raise 422 for unknown values."""
    unique_scopes = list(dict.fromkeys(scopes))
    unknown = sorted(set(unique_scopes) - VALID_API_KEY_SCOPES)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Unknown API key scope.",
                "unknown_scopes": unknown,
                "allowed_scopes": sorted(VALID_API_KEY_SCOPES),
            },
        )
    return unique_scopes


async def create_api_key(
    db: AsyncSession,
    developer_account: DeveloperAccount,
    payload: ApiKeyCreateRequest,
) -> tuple[ApiKey, str]:
    """Create an API key and return the raw secret exactly once."""
    account_id = developer_account.id
    user_id = developer_account.user_id
    scopes = _validate_scopes(payload.scopes)
    raw_key = _generate_raw_api_key()
    key_hash = _hash_api_key(raw_key)

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        api_key = ApiKey(
            developer_account_id=account_id,
            name=payload.name,
            key_prefix=raw_key[:API_KEY_PREFIX_LENGTH],
            key_hash=key_hash,
            scopes=scopes,
            expires_at=payload.expires_at,
        )
        db.add(api_key)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=user_id,
            action="api_key_created",
            target_type="api_key",
            target_id=api_key.id,
            metadata={
                "developer_account_id": str(account_id),
                "key_prefix": api_key.key_prefix,
                "scopes": api_key.scopes,
            },
        )
    return api_key, raw_key


async def list_api_keys(
    db: AsyncSession,
    developer_account: DeveloperAccount,
) -> list[ApiKey]:
    """Return API key metadata for the active Developer account."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.developer_account_id == developer_account.id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def update_api_key(
    db: AsyncSession,
    developer_account: DeveloperAccount,
    api_key_id: UUID,
    payload: ApiKeyUpdateRequest,
) -> ApiKey:
    """Update API key label metadata for the owning Developer account."""
    account_id = developer_account.id
    user_id = developer_account.user_id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        api_key = await db.scalar(
            select(ApiKey)
            .where(
                ApiKey.id == api_key_id,
                ApiKey.developer_account_id == account_id,
            )
            .with_for_update()
        )
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found.",
            )
        api_key.name = payload.name
        await write_audit(
            db=db,
            actor_id=user_id,
            action="api_key_updated",
            target_type="api_key",
            target_id=api_key.id,
            metadata={"key_prefix": api_key.key_prefix},
        )
    return api_key


async def revoke_api_key(
    db: AsyncSession,
    developer_account: DeveloperAccount,
    api_key_id: UUID,
) -> ApiKey:
    """Revoke an API key owned by the active Developer account."""
    account_id = developer_account.id
    user_id = developer_account.user_id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        api_key = await db.scalar(
            select(ApiKey)
            .where(
                ApiKey.id == api_key_id,
                ApiKey.developer_account_id == account_id,
            )
            .with_for_update()
        )
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API key not found.",
            )
        if api_key.status != "revoked":
            api_key.status = "revoked"
            api_key.revoked_at = datetime.now(UTC)
            await write_audit(
                db=db,
                actor_id=user_id,
                action="api_key_revoked",
                target_type="api_key",
                target_id=api_key.id,
                metadata={"key_prefix": api_key.key_prefix},
            )
    return api_key
