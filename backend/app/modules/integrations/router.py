"""Integrations API router.

Connection lifecycle endpoints for external file providers. The callback
is public — the provider redirects the contributor's browser there with
no Authorization header — so it is bound to the initiating user by the
signed connector state cookie and rate-limited by client IP.

Maps to: Framework Artifact Connectors design (Phase A).
"""

from __future__ import annotations

from typing import Annotated, cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import Settings, get_settings
from app.core.cookies import (
    CONNECTOR_STATE_COOKIE_NAME,
    clear_connector_state_cookie,
    read_connector_state_value,
    set_connector_state_cookie,
)
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.redis import get_redis
from app.integrations.google_drive import GoogleDriveError
from app.modules.auth.models import User
from app.modules.integrations import service
from app.modules.integrations.schemas import (
    ConnectorConnectResponse,
    ConnectorFilesResponse,
    ConnectorsResponse,
)

router = APIRouter(prefix="/integrations", tags=["Integrations"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
ContributorUser = Annotated[User, Depends(require_role("contributor"))]
RedisClient = Annotated[Redis, Depends(get_redis)]
AppSettings = Annotated[Settings, Depends(get_settings)]

# The callback is unauthenticated, so throttle it by client IP.
CALLBACK_LIMITER = RateLimiter(namespace="connector_callback", limit=10, window=600)


def _frontend_redirect(settings: Settings, provider: str, outcome: str) -> str:
    """Build the settings-page URL the callback sends the browser back to.

    The API is served under the frontend origin's ``/api`` proxy, so the
    Drive redirect URI carries the origin the contributor is browsing on.
    Falls back to the first CORS origin in split-host setups.
    """
    origin = ""
    if settings.google_drive_redirect_uri:
        parts = urlsplit(settings.google_drive_redirect_uri)
        origin = f"{parts.scheme}://{parts.netloc}"
    if not origin:
        origin = settings.cors_allowed_origins.split(",")[0].strip()
    return f"{origin}/settings/integrations?connector={provider}&status={outcome}"


@router.get(
    "/connectors",
    response_model=ConnectorsResponse,
    summary="List connector providers and connection status",
    description=(
        "Report every supported external file provider with the "
        "authenticated user's connection status and account email."
    ),
)
async def list_connectors(
    db: DatabaseSession,
    user: CurrentUser,
) -> ConnectorsResponse:
    """List supported providers with the user's connection status."""
    return await service.list_connector_statuses(db, user_id=user.id)


@router.post(
    "/connectors/{provider}/connect",
    response_model=ConnectorConnectResponse,
    summary="Start connecting an external file provider",
    description=(
        "Begin the OAuth consent flow for a provider. Returns the "
        "authorization URL to navigate to and seals the CSRF state and "
        "PKCE verifier in a signed, HttpOnly cookie."
    ),
)
async def connect_provider(
    provider: str,
    contributor: ContributorUser,
    settings: AppSettings,
) -> JSONResponse:
    """Start the consent flow and set the signed connector state cookie."""
    authorization_url, state, verifier = service.start_connect(provider, settings)
    response = JSONResponse(content={"authorization_url": authorization_url})
    set_connector_state_cookie(
        response,
        state=state,
        verifier=verifier,
        user_id=str(contributor.id),
        settings=settings,
    )
    return response


@router.get(
    "/connectors/{provider}/callback",
    summary="Complete a provider consent round trip",
    description=(
        "Public browser-redirect target for the provider's consent screen. "
        "Validates the signed state cookie, redeems the authorization code, "
        "stores the encrypted tokens, and redirects back to settings."
    ),
)
async def provider_callback(
    provider: str,
    request: Request,
    db: DatabaseSession,
    redis: RedisClient,
    settings: AppSettings,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    connector_state: Annotated[
        str | None, Cookie(alias=CONNECTOR_STATE_COOKIE_NAME)
    ] = None,
) -> Response:
    """Validate state, redeem the code, upsert the connection, redirect."""
    client_ip = request.client.host if request.client else "unknown"
    await CALLBACK_LIMITER.check(cast(RedisCounter, redis), client_ip)

    if error is not None:
        # The user declined consent at Google — not a security event.
        response: Response = RedirectResponse(
            url=_frontend_redirect(settings, provider, "denied"),
            status_code=status.HTTP_302_FOUND,
        )
        clear_connector_state_cookie(response, settings)
        return response

    payload = read_connector_state_value(connector_state, settings)
    if (
        payload is None
        or not state
        or payload.get("state") != state
        or not code
        or not isinstance(payload.get("user_id"), str)
    ):
        logger.bind(module="integrations", action="connector_callback").warning(
            "connector_state_invalid"
        )
        if db.in_transaction():
            await db.rollback()
        async with db.begin():
            await write_audit(
                db=db,
                actor_id=None,
                action="connector_state_invalid",
                target_type="oauth_connection",
                metadata={"provider": provider},
            )
        response = JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid connector state."},
        )
        clear_connector_state_cookie(response, settings)
        return response

    user_id = UUID(str(payload["user_id"]))
    verifier = str(payload.get("verifier", ""))
    try:
        await service.complete_callback(
            db,
            provider_segment=provider,
            user_id=user_id,
            code=code,
            verifier=verifier,
            settings=settings,
        )
    except GoogleDriveError:
        logger.bind(
            module="integrations",
            action="connector_callback",
            user_id=str(user_id),
        ).error("connector_exchange_failed")
        response = RedirectResponse(
            url=_frontend_redirect(settings, provider, "error"),
            status_code=status.HTTP_302_FOUND,
        )
        clear_connector_state_cookie(response, settings)
        return response

    response = RedirectResponse(
        url=_frontend_redirect(settings, provider, "connected"),
        status_code=status.HTTP_302_FOUND,
    )
    clear_connector_state_cookie(response, settings)
    return response


@router.delete(
    "/connectors/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect an external file provider",
    description=(
        "Best-effort token revocation at the provider, then mark the "
        "connection revoked and discard the stored tokens. Idempotent."
    ),
)
async def disconnect_provider(
    provider: str,
    contributor: ContributorUser,
    db: DatabaseSession,
) -> None:
    """Revoke the contributor's connection to a provider."""
    await service.revoke_connection(
        db, user_id=contributor.id, provider_segment=provider
    )


@router.get(
    "/connectors/{provider}/files",
    response_model=ConnectorFilesResponse,
    summary="Browse files in a connected provider",
    description=(
        "One page of the contributor's files and folders from the "
        "connected provider, folders first. Browsing is scoped to "
        "folder_id (root when omitted); a query searches globally."
    ),
)
async def list_connector_files(
    provider: str,
    contributor: ContributorUser,
    db: DatabaseSession,
    query: Annotated[str | None, Query(max_length=256)] = None,
    page_token: Annotated[str | None, Query(max_length=512)] = None,
    folder_id: Annotated[str | None, Query(max_length=256)] = None,
) -> ConnectorFilesResponse:
    """Browse the connected provider's files for the import picker."""
    return await service.browse_files(
        db,
        user_id=contributor.id,
        provider_segment=provider,
        query=query,
        page_token=page_token,
        folder_id=folder_id,
    )
