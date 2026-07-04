"""Integrations service layer.

Connection lifecycle for external file providers (Google Drive in v1):
start the consent flow, complete the callback, refresh tokens on demand,
browse files, revoke, and GDPR-export connection metadata. Tokens are
Fernet-encrypted before persistence and never logged or returned.

Maps to: Framework Artifact Connectors design (Phase A).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import Settings
from app.core.security import decrypt_connector_token, encrypt_connector_token
from app.integrations import google_drive
from app.integrations.google_drive import (
    DRIVE_SCOPE,
    EXPORT_MIME_MAP,
    FOLDER_MIME_TYPE,
    GoogleDriveAuthError,
    GoogleDriveError,
)
from app.integrations.google_oauth import generate_pkce_pair, generate_state
from app.modules.integrations.models import OAuthConnection
from app.modules.integrations.schemas import (
    ConnectorFileItem,
    ConnectorFilesResponse,
    ConnectorsResponse,
    ConnectorStatusItem,
)

# URL path segment -> stored provider value. v1 ships Google Drive only,
# but the URL surface stays provider-generic.
PROVIDERS: dict[str, str] = {"google-drive": "google_drive"}

# Refresh the access token when it expires within this window so a
# just-about-to-expire token never reaches a Drive call.
_TOKEN_REFRESH_LEEWAY_SECONDS = 60


def resolve_provider(provider_segment: str) -> str:
    """Map a URL provider segment to its stored value or raise 404."""
    stored = PROVIDERS.get(provider_segment)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown provider.",
        )
    return stored


def _reauth_required_error() -> HTTPException:
    """Build the 409 returned when a connection needs re-authorization."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": "reauth_required",
            "message": "The connection is no longer authorized. Reconnect it.",
        },
    )


async def list_connector_statuses(
    db: AsyncSession, *, user_id: UUID
) -> ConnectorsResponse:
    """Report the user's connection status for every supported provider."""
    rows = (
        (
            await db.execute(
                select(OAuthConnection).where(OAuthConnection.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    by_provider = {row.provider: row for row in rows}
    connectors: list[ConnectorStatusItem] = []
    for segment, stored in PROVIDERS.items():
        row = by_provider.get(stored)
        if row is None or row.status == "revoked":
            connectors.append(
                ConnectorStatusItem(provider=segment, connected=False)
            )
        else:
            connectors.append(
                ConnectorStatusItem(
                    provider=segment,
                    connected=True,
                    connection_id=row.id,
                    status=row.status,
                    account_email=row.provider_account_email,
                )
            )
    return ConnectorsResponse(connectors=connectors)


def start_connect(
    provider_segment: str,
    settings: Settings | None = None,
) -> tuple[str, str, str]:
    """Start the consent flow for a provider.

    Returns:
        Tuple of (authorization_url, state, pkce_verifier). The caller
        seals state + verifier into the signed connector cookie.

    Raises:
        HTTPException(404): Unknown provider.
        HTTPException(503): Google client not configured.
    """
    resolve_provider(provider_segment)
    state = generate_state()
    pkce = generate_pkce_pair()
    try:
        url = google_drive.build_drive_authorization_url(
            state=state,
            code_challenge=pkce.challenge,
            settings=settings,
        )
    except GoogleDriveError as exc:
        logger.bind(module="integrations", action="connector_connect").error(
            "connector_unconfigured"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The connector is not configured.",
        ) from exc
    return url, state, pkce.verifier


async def complete_callback(
    db: AsyncSession,
    *,
    provider_segment: str,
    user_id: UUID,
    code: str,
    verifier: str,
    settings: Settings | None = None,
) -> None:
    """Redeem the callback code and upsert the user's connection.

    Reconnecting replaces the stored tokens on the existing row rather
    than creating a second connection (unique on user + provider).

    Raises:
        HTTPException(404): Unknown provider.
        GoogleDriveError: When the token exchange fails (caller redirects
            with an error status rather than surfacing a JSON error).
    """
    stored_provider = resolve_provider(provider_segment)
    tokens = await google_drive.exchange_drive_code(
        code=code, verifier=verifier, settings=settings
    )
    account_email = await google_drive.fetch_drive_account_email(tokens.access_token)

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        connection = await db.scalar(
            select(OAuthConnection).where(
                OAuthConnection.user_id == user_id,
                OAuthConnection.provider == stored_provider,
            )
        )
        if connection is None:
            connection = OAuthConnection(
                user_id=user_id,
                provider=stored_provider,
                scopes=DRIVE_SCOPE,
            )
            db.add(connection)
        connection.access_token_encrypted = encrypt_connector_token(
            tokens.access_token
        )
        if tokens.refresh_token is not None:
            connection.refresh_token_encrypted = encrypt_connector_token(
                tokens.refresh_token
            )
        connection.token_expires_at = tokens.expires_at
        connection.provider_account_email = account_email
        connection.scopes = DRIVE_SCOPE
        connection.status = "active"
        await db.flush()
        await write_audit(
            db=db,
            actor_id=user_id,
            action="connector_connected",
            target_type="oauth_connection",
            target_id=connection.id,
            metadata={"provider": stored_provider},
        )
    logger.bind(
        module="integrations",
        action="connector_connected",
        user_id=str(user_id),
        provider=stored_provider,
    ).info("connector_connected")


async def revoke_connection(
    db: AsyncSession,
    *,
    user_id: UUID,
    provider_segment: str,
) -> None:
    """Revoke a connection: best-effort at Google, then locally.

    Idempotent — revoking an already-revoked connection returns cleanly.

    Raises:
        HTTPException(404): Unknown provider or no connection row.
    """
    stored_provider = resolve_provider(provider_segment)
    connection = await db.scalar(
        select(OAuthConnection).where(
            OAuthConnection.user_id == user_id,
            OAuthConnection.provider == stored_provider,
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found.",
        )
    connection_id = connection.id
    stored_tokens = [
        encrypted
        for encrypted in (
            connection.access_token_encrypted,
            connection.refresh_token_encrypted,
        )
        if encrypted
    ]
    for encrypted in stored_tokens:
        await google_drive.revoke_drive_token(decrypt_connector_token(encrypted))

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        connection = await db.scalar(
            select(OAuthConnection).where(OAuthConnection.id == connection_id)
        )
        if connection is None:
            return
        connection.status = "revoked"
        connection.access_token_encrypted = None
        connection.refresh_token_encrypted = None
        connection.token_expires_at = None
        await write_audit(
            db=db,
            actor_id=user_id,
            action="connector_revoked",
            target_type="oauth_connection",
            target_id=connection_id,
            metadata={"provider": stored_provider},
        )
    logger.bind(
        module="integrations",
        action="connector_revoked",
        user_id=str(user_id),
        provider=stored_provider,
    ).info("connector_revoked")


async def _mark_reauth_required(db: AsyncSession, connection_id: UUID) -> None:
    """Persist that a connection's grant is dead and needs re-consent."""
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        connection = await db.scalar(
            select(OAuthConnection).where(OAuthConnection.id == connection_id)
        )
        if connection is not None:
            connection.status = "reauth_required"


async def get_active_connection_with_fresh_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    provider: str | None = None,
    connection_id: UUID | None = None,
) -> tuple[OAuthConnection, str]:
    """Load the user's connection and return a usable decrypted access token.

    Exactly one selector must be given: ``provider`` (stored value, used by
    browse) or ``connection_id`` (used by copy-in). Refreshes the access
    token when it expires within 60 seconds, persisting the new encrypted
    token and expiry.

    Returns:
        Tuple of (connection, decrypted access token).

    Raises:
        ValueError: If neither or both selectors are given.
        HTTPException(404): Connection absent or owned by another user.
        HTTPException(409): Connection revoked or needs re-authorization
            (``error_code: reauth_required``).
    """
    if (provider is None) == (connection_id is None):
        raise ValueError("Pass exactly one of provider or connection_id.")
    conditions = [OAuthConnection.user_id == user_id]
    if provider is not None:
        conditions.append(OAuthConnection.provider == provider)
    if connection_id is not None:
        conditions.append(OAuthConnection.id == connection_id)
    connection = await db.scalar(select(OAuthConnection).where(*conditions))
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found.",
        )
    if connection.status == "reauth_required":
        raise _reauth_required_error()
    if connection.status == "revoked" or not connection.access_token_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "connection_revoked",
                "message": "The connection was revoked. Reconnect it.",
            },
        )

    expires_at = connection.token_expires_at
    needs_refresh = expires_at is not None and expires_at <= datetime.now(
        UTC
    ) + timedelta(seconds=_TOKEN_REFRESH_LEEWAY_SECONDS)
    if not needs_refresh:
        return connection, decrypt_connector_token(connection.access_token_encrypted)

    connection_id_value = connection.id
    if not connection.refresh_token_encrypted:
        await _mark_reauth_required(db, connection_id_value)
        raise _reauth_required_error()
    refresh_token = decrypt_connector_token(connection.refresh_token_encrypted)
    try:
        tokens = await google_drive.refresh_drive_tokens(refresh_token=refresh_token)
    except GoogleDriveAuthError:
        await _mark_reauth_required(db, connection_id_value)
        raise _reauth_required_error() from None

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        refreshed = await db.scalar(
            select(OAuthConnection).where(OAuthConnection.id == connection_id_value)
        )
        if refreshed is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found.",
            )
        refreshed.access_token_encrypted = encrypt_connector_token(
            tokens.access_token
        )
        if tokens.refresh_token is not None:
            refreshed.refresh_token_encrypted = encrypt_connector_token(
                tokens.refresh_token
            )
        refreshed.token_expires_at = tokens.expires_at
        connection = refreshed
    return connection, tokens.access_token


def _is_importable(mime_type: str) -> bool:
    """Whether a Drive file can become an Artifact (directly or via export)."""
    # Local import: frameworks depends on integrations for copy-in, so the
    # reverse import must stay function-scoped to avoid a cycle.
    from app.modules.frameworks.service import ALLOWED_ARTIFACT_MIME_TYPES

    return mime_type in ALLOWED_ARTIFACT_MIME_TYPES or mime_type in EXPORT_MIME_MAP


async def browse_files(
    db: AsyncSession,
    *,
    user_id: UUID,
    provider_segment: str,
    query: str | None,
    page_token: str | None,
    folder_id: str | None = None,
) -> ConnectorFilesResponse:
    """List the user's Drive files and folders for the import picker.

    Raises:
        HTTPException(404): Unknown provider or no connection.
        HTTPException(409): Connection needs re-authorization.
        HTTPException(502): Drive API failure.
    """
    stored_provider = resolve_provider(provider_segment)
    connection, access_token = await get_active_connection_with_fresh_token(
        db, user_id=user_id, provider=stored_provider
    )
    try:
        page = await google_drive.list_drive_files(
            access_token=access_token,
            query=query,
            page_token=page_token,
            folder_id=folder_id,
        )
    except GoogleDriveAuthError:
        await _mark_reauth_required(db, connection.id)
        raise _reauth_required_error() from None
    except GoogleDriveError as exc:
        logger.bind(
            module="integrations",
            action="browse_files",
            user_id=str(user_id),
            provider=stored_provider,
        ).error("drive_browse_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    files: list[ConnectorFileItem] = []
    for raw in page["files"]:
        mime_type = str(raw.get("mimeType", ""))
        size_value = raw.get("size")
        is_folder = mime_type == FOLDER_MIME_TYPE
        files.append(
            ConnectorFileItem(
                id=str(raw.get("id", "")),
                name=str(raw.get("name", "")),
                mime_type=mime_type,
                size=int(size_value) if size_value is not None else None,
                modified_time=raw.get("modifiedTime"),
                icon_link=raw.get("iconLink"),
                importable=not is_folder and _is_importable(mime_type),
                is_folder=is_folder,
            )
        )
    return ConnectorFilesResponse(
        files=files, next_page_token=page.get("next_page_token")
    )


async def export_user_connections(
    db: AsyncSession, *, user_id: UUID
) -> list[dict[str, Any]]:
    """GDPR export: the user's connector grants — metadata only, never tokens."""
    rows = (
        (
            await db.execute(
                select(OAuthConnection).where(OAuthConnection.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "provider": row.provider,
            "account_email": row.provider_account_email,
            "status": row.status,
            "connected_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
