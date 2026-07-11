"""Google Drive read-only provider client for artifact connectors.

Backend authorization-code flow with PKCE against the same Google OAuth
app as login, but with the ``drive.readonly`` scope and offline access so
we can refresh tokens server-side. All fetches go only to fixed Google
hosts; tokens are never logged.

Maps to: Framework Artifact Connectors design (Phase A).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
from loguru import logger

from app.core.config import Settings, get_settings
from app.integrations.google_oauth import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_TOKEN_ENDPOINT,
)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_DRIVE_TIMEOUT_SECONDS = 30.0
_DRIVE_PAGE_SIZE = 25
_THUMBNAIL_TIMEOUT_SECONDS = 15.0
THUMBNAIL_ALLOWED_HOST_SUFFIXES = (".googleusercontent.com", ".google.com")

# Google-native document types cannot be downloaded raw; they are exported
# to the mapped Office format (and get the mapped file extension).
EXPORT_MIME_MAP: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
    ),
}


class GoogleDriveError(RuntimeError):
    """Raised when a Google Drive request fails or is misconfigured."""


class GoogleDriveAuthError(GoogleDriveError):
    """Raised when Drive credentials are invalid (401 / invalid_grant).

    Callers mark the stored connection ``reauth_required`` on this error.
    """


class DriveFileTooLargeError(GoogleDriveError):
    """Raised when a Drive download exceeds the caller's byte budget."""


class GoogleDriveNotFoundError(GoogleDriveError):
    """Raised when a Drive file is missing or no longer accessible (404)."""


@dataclass(frozen=True)
class DriveTokens:
    """Access/refresh token pair returned by Google's token endpoint."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime


def build_drive_authorization_url(
    *,
    state: str,
    code_challenge: str,
    settings: Settings | None = None,
) -> str:
    """Build the Google consent URL for the Drive read-only connector.

    Args:
        state: Opaque CSRF token echoed back to the callback.
        code_challenge: S256 PKCE challenge derived from the stored verifier.
        settings: Application settings (defaults to the process settings).

    Returns:
        The Google authorization URL to redirect the contributor to.

    Raises:
        GoogleDriveError: If the Google client or Drive redirect URI is
            not configured.
    """
    resolved = settings or get_settings()
    if not resolved.google_client_id or not resolved.google_drive_redirect_uri:
        raise GoogleDriveError("Google Drive connector is not configured.")
    params = {
        "client_id": resolved.google_client_id,
        "redirect_uri": resolved.google_drive_redirect_uri,
        "response_type": "code",
        "scope": DRIVE_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # Offline access + forced consent so Google issues a refresh token
        # we can use for silent server-side renewal.
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def _tokens_from_response(
    payload: dict[str, Any],
    fallback_refresh_token: str | None,
) -> DriveTokens:
    """Build DriveTokens from a token-endpoint payload.

    Google omits ``refresh_token`` on refresh responses; the previously
    stored refresh token stays valid, so keep it.
    """
    expires_in = int(payload.get("expires_in", 0))
    return DriveTokens(
        access_token=str(payload["access_token"]),
        refresh_token=payload.get("refresh_token") or fallback_refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


async def _post_token_endpoint(data: dict[str, str], action: str) -> dict[str, Any]:
    """POST to Google's token endpoint, translating failures to typed errors."""
    try:
        async with httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client:
            response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
    except httpx.HTTPError as exc:
        logger.bind(module="integrations", action=action).error(
            "google_token_endpoint_unreachable"
        )
        raise GoogleDriveError("Google token endpoint unreachable.") from exc
    if response.status_code >= 400:
        body: dict[str, Any] = {}
        try:
            body = response.json()
        except ValueError:
            body = {}
        error_code = str(body.get("error", ""))
        logger.bind(module="integrations", action=action).warning(
            "google_token_endpoint_rejected",
            status_code=response.status_code,
            error_code=error_code,
        )
        if response.status_code == 401 or error_code == "invalid_grant":
            raise GoogleDriveAuthError("Google Drive authorization is no longer valid.")
        raise GoogleDriveError("Google rejected the token request.")
    return dict(response.json())


async def exchange_drive_code(
    *,
    code: str,
    verifier: str,
    settings: Settings | None = None,
) -> DriveTokens:
    """Exchange an authorization code for Drive tokens, server-side.

    Args:
        code: Authorization code returned by Google to the callback.
        verifier: PKCE verifier sealed in the connector state cookie.
        settings: Application settings (provides Google client config).

    Returns:
        The granted DriveTokens.

    Raises:
        GoogleDriveError: If unconfigured or Google rejects the request.
        GoogleDriveAuthError: On ``invalid_grant`` / 401.
    """
    resolved = settings or get_settings()
    if (
        not resolved.google_client_id
        or not resolved.google_client_secret
        or not resolved.google_drive_redirect_uri
    ):
        raise GoogleDriveError("Google Drive connector is not configured.")
    payload = await _post_token_endpoint(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": resolved.google_client_id,
            "client_secret": resolved.google_client_secret.get_secret_value(),
            "redirect_uri": resolved.google_drive_redirect_uri,
        },
        action="exchange_drive_code",
    )
    return _tokens_from_response(payload, fallback_refresh_token=None)


async def refresh_drive_tokens(
    *,
    refresh_token: str,
    settings: Settings | None = None,
) -> DriveTokens:
    """Obtain a fresh access token from a stored refresh token.

    Keeps the passed refresh token when Google's response omits one.

    Raises:
        GoogleDriveAuthError: When the refresh token is revoked/expired.
        GoogleDriveError: On other failures.
    """
    resolved = settings or get_settings()
    if not resolved.google_client_id or not resolved.google_client_secret:
        raise GoogleDriveError("Google Drive connector is not configured.")
    payload = await _post_token_endpoint(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": resolved.google_client_id,
            "client_secret": resolved.google_client_secret.get_secret_value(),
        },
        action="refresh_drive_tokens",
    )
    return _tokens_from_response(payload, fallback_refresh_token=refresh_token)


async def revoke_drive_token(token: str) -> None:
    """Best-effort revocation of a Drive token at Google.

    Never raises: revocation failure must not block disconnecting locally.
    """
    try:
        async with httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client:
            response = await client.post(
                GOOGLE_REVOKE_ENDPOINT, data={"token": token}
            )
    except httpx.HTTPError:
        logger.bind(module="integrations", action="revoke_drive_token").warning(
            "google_revoke_unreachable"
        )
        return
    if response.status_code >= 400:
        logger.bind(module="integrations", action="revoke_drive_token").warning(
            "google_revoke_rejected", status_code=response.status_code
        )


def _raise_for_drive_response(response: httpx.Response, action: str) -> None:
    """Translate a failed Drive API response into a typed error."""
    logger.bind(module="integrations", action=action).warning(
        "drive_api_error", status_code=response.status_code
    )
    if response.status_code in (401, 403):
        raise GoogleDriveAuthError("Google Drive authorization is no longer valid.")
    if response.status_code == 404:
        raise GoogleDriveNotFoundError("Google Drive file not found.")
    raise GoogleDriveError("Google Drive request failed.")


async def fetch_drive_account_email(access_token: str) -> str | None:
    """Fetch the connected Google account's email for display.

    Returns None when the field is unavailable rather than failing the
    connect flow over a display-only value.
    """
    try:
        async with httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{DRIVE_API_BASE}/about",
                params={"fields": "user(emailAddress)"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    payload = response.json()
    user = payload.get("user")
    if not isinstance(user, dict):
        return None
    email = user.get("emailAddress")
    return str(email) if email else None


def _escape_drive_query(term: str) -> str:
    """Escape a user search term for embedding in a Drive ``q`` string."""
    return term.replace("\\", "\\\\").replace("'", "\\'")


async def list_drive_files(
    *,
    access_token: str,
    query: str | None,
    page_token: str | None,
    folder_id: str | None = None,
) -> dict[str, Any]:
    """List Drive files and folders for the import picker, folders first.

    Two modes: a search term runs globally across the user's Drive (so
    shared files stay findable), while browsing without one is scoped to
    the children of ``folder_id`` (My Drive root when omitted).

    Args:
        access_token: A valid Drive access token.
        query: Optional name-contains search term (escaped before use).
            When given, ``folder_id`` is ignored — search is global.
        page_token: Optional cursor from a previous page.
        folder_id: Optional folder to browse into (escaped before use).

    Returns:
        Dict with ``files`` (raw Drive file dicts) and ``next_page_token``.

    Raises:
        GoogleDriveAuthError: On 401/403 from Drive.
        GoogleDriveError: On other failures.
    """
    clauses = ["trashed = false"]
    if query:
        clauses.append(f"name contains '{_escape_drive_query(query)}'")
    else:
        parent = _escape_drive_query(folder_id) if folder_id else "root"
        clauses.append(f"'{parent}' in parents")
    params: dict[str, str] = {
        "q": " and ".join(clauses),
        "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,iconLink)",
        "pageSize": str(_DRIVE_PAGE_SIZE),
        "orderBy": "folder,modifiedTime desc",
    }
    if page_token:
        params["pageToken"] = page_token
    try:
        async with httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{DRIVE_API_BASE}/files",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise GoogleDriveError("Google Drive unreachable.") from exc
    if response.status_code >= 400:
        _raise_for_drive_response(response, action="list_drive_files")
    payload = response.json()
    return {
        "files": payload.get("files", []),
        "next_page_token": payload.get("nextPageToken"),
    }


async def get_drive_file_metadata(
    *,
    access_token: str,
    file_id: str,
) -> dict[str, Any]:
    """Fetch id/name/mimeType/size metadata for one Drive file.

    Raises:
        GoogleDriveAuthError: On 401/403 from Drive.
        GoogleDriveError: On other failures.
    """
    try:
        async with httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}",
                params={"fields": "id,name,mimeType,size,modifiedTime"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise GoogleDriveError("Google Drive unreachable.") from exc
    if response.status_code >= 400:
        _raise_for_drive_response(response, action="get_drive_file_metadata")
    return dict(response.json())


async def fetch_drive_source_state(
    *,
    access_token: str,
    file_id: str,
) -> tuple[str, str | None]:
    """Fetch the current revision marker and thumbnail link for a Drive file."""
    try:
        async with httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}",
                params={"fields": "modifiedTime,thumbnailLink"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        raise GoogleDriveError("Google Drive unreachable.") from exc
    if response.status_code >= 400:
        _raise_for_drive_response(response, action="fetch_drive_source_state")
    payload = response.json()
    modified_time = str(payload.get("modifiedTime", ""))
    thumbnail_link = payload.get("thumbnailLink")
    return modified_time, (str(thumbnail_link) if thumbnail_link else None)


async def download_drive_file(
    *,
    access_token: str,
    file_id: str,
    export_mime: str | None,
    max_bytes: int,
) -> bytes:
    """Download (or export) a Drive file's bytes within a byte budget.

    Streams the body and aborts as soon as the accumulated size exceeds
    ``max_bytes`` — Google-native exports have unknown size up front, so
    the budget cannot be checked from metadata alone.

    Args:
        access_token: A valid Drive access token.
        file_id: The Drive file to fetch.
        export_mime: Export MIME type for Google-native files, or None to
            download the raw bytes (``alt=media``).
        max_bytes: Hard byte budget for the download.

    Returns:
        The file content.

    Raises:
        DriveFileTooLargeError: When the stream exceeds ``max_bytes``.
        GoogleDriveAuthError: On 401/403 from Drive.
        GoogleDriveError: On other failures.
    """
    if export_mime is not None:
        url = f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}/export"
        params = {"mimeType": export_mime}
    else:
        url = f"{DRIVE_API_BASE}/files/{quote(file_id, safe='')}"
        params = {"alt": "media"}
    chunks: list[bytes] = []
    received = 0
    try:
        async with (
            httpx.AsyncClient(timeout=_DRIVE_TIMEOUT_SECONDS) as client,
            client.stream(
                "GET",
                url,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                _raise_for_drive_response(response, action="download_drive_file")
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > max_bytes:
                    raise DriveFileTooLargeError(
                        "Drive file exceeds the framework artifact size budget."
                    )
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise GoogleDriveError("Google Drive unreachable.") from exc
    return b"".join(chunks)


def _thumbnail_host_allowed(thumbnail_link: str) -> bool:
    """Return whether the thumbnail host is on the Google allowlist."""
    host = urlsplit(thumbnail_link).hostname or ""
    return any(
        host == suffix.lstrip(".") or host.endswith(suffix)
        for suffix in THUMBNAIL_ALLOWED_HOST_SUFFIXES
    )


async def download_drive_thumbnail(
    *,
    thumbnail_link: str,
    access_token: str,
    max_bytes: int,
) -> bytes:
    """Download a Drive thumbnail within a byte budget after host validation."""
    if not _thumbnail_host_allowed(thumbnail_link):
        logger.bind(module="integrations", action="download_drive_thumbnail").warning(
            "thumbnail_host_rejected"
        )
        raise GoogleDriveError("Thumbnail host is not allowed.")

    chunks: list[bytes] = []
    received = 0
    try:
        async with (
            httpx.AsyncClient(timeout=_THUMBNAIL_TIMEOUT_SECONDS) as client,
            client.stream(
                "GET",
                thumbnail_link,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise GoogleDriveError("Thumbnail fetch failed.")
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > max_bytes:
                    raise DriveFileTooLargeError("Thumbnail exceeds the byte budget.")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise GoogleDriveError("Google thumbnail unreachable.") from exc
    return b"".join(chunks)
