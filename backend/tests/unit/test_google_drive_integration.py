"""Unit tests for the Google Drive provider client (connectors Phase A)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.google_drive import (
    DRIVE_SCOPE,
    EXPORT_MIME_MAP,
    DriveFileTooLargeError,
    GoogleDriveAuthError,
    build_drive_authorization_url,
    download_drive_file,
    exchange_drive_code,
    fetch_drive_account_email,
    list_drive_files,
    refresh_drive_tokens,
)

pytestmark = pytest.mark.asyncio

DRIVE_SETTINGS = Settings(
    GOOGLE_CLIENT_ID="client-abc.apps.googleusercontent.com",
    GOOGLE_CLIENT_SECRET="gclient_secret",
    GOOGLE_DRIVE_REDIRECT_URI=(
        "https://auracles.space/v1/integrations/connectors/google-drive/callback"
    ),
)

TOKEN_URL = "https://oauth2.googleapis.com/token"


def test_authorization_url_carries_offline_drive_consent() -> None:
    """The consent URL requests offline read-only Drive access with PKCE."""
    url = build_drive_authorization_url(
        state="state-1", code_challenge="challenge-1", settings=DRIVE_SETTINGS
    )
    query = parse_qs(urlsplit(url).query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["scope"] == [DRIVE_SCOPE]
    assert query["code_challenge"] == ["challenge-1"]
    assert query["redirect_uri"] == [DRIVE_SETTINGS.google_drive_redirect_uri]


@respx.mock
async def test_exchange_drive_code_returns_tokens() -> None:
    """Code exchange posts the PKCE verifier and computes expiry."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
        )
    )
    tokens = await exchange_drive_code(
        code="code-1", verifier="verifier-1", settings=DRIVE_SETTINGS
    )
    body = parse_qs(route.calls.last.request.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code_verifier"] == ["verifier-1"]
    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert tokens.expires_at is not None


@respx.mock
async def test_refresh_retains_prior_refresh_token() -> None:
    """A refresh response without refresh_token keeps the stored one."""
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "new-at", "expires_in": 3600}
        )
    )
    tokens = await refresh_drive_tokens(
        refresh_token="stored-rt", settings=DRIVE_SETTINGS
    )
    assert tokens.access_token == "new-at"
    assert tokens.refresh_token == "stored-rt"


@respx.mock
async def test_refresh_invalid_grant_raises_auth_error() -> None:
    """An invalid_grant refresh failure surfaces as an auth error."""
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(GoogleDriveAuthError):
        await refresh_drive_tokens(refresh_token="dead-rt", settings=DRIVE_SETTINGS)


@respx.mock
async def test_list_drive_files_search_is_global_and_escaped() -> None:
    """A search term produces a global, escaped query with no parent scope."""
    route = respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"id": "f1"}], "nextPageToken": "cursor"}
        )
    )
    page = await list_drive_files(
        access_token="at", query="bob's plan", page_token=None, folder_id="ignored"
    )
    params = parse_qs(urlsplit(str(route.calls.last.request.url)).query)
    q = params["q"][0]
    assert "trashed = false" in q
    assert "name contains 'bob\\'s plan'" in q
    assert "in parents" not in q
    assert params["orderBy"] == ["folder,modifiedTime desc"]
    assert page["files"] == [{"id": "f1"}]
    assert page["next_page_token"] == "cursor"


@respx.mock
async def test_list_drive_files_browses_my_drive_root_by_default() -> None:
    """Without a search term or folder, browsing lists the My Drive root."""
    route = respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    await list_drive_files(
        access_token="at", query=None, page_token=None, folder_id=None
    )
    q = parse_qs(urlsplit(str(route.calls.last.request.url)).query)["q"][0]
    assert "'root' in parents" in q
    assert "name contains" not in q


@respx.mock
async def test_list_drive_files_scopes_to_folder() -> None:
    """A folder id scopes browsing to that folder's children, escaped."""
    route = respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    await list_drive_files(
        access_token="at", query=None, page_token=None, folder_id="fold'er-1"
    )
    q = parse_qs(urlsplit(str(route.calls.last.request.url)).query)["q"][0]
    assert "'fold\\'er-1' in parents" in q


@respx.mock
async def test_download_uses_alt_media_for_binary_files() -> None:
    """Raw binary files download via alt=media."""
    route = respx.get("https://www.googleapis.com/drive/v3/files/f1").mock(
        return_value=httpx.Response(200, content=b"PDFBYTES")
    )
    body = await download_drive_file(
        access_token="at", file_id="f1", export_mime=None, max_bytes=1024
    )
    assert body == b"PDFBYTES"
    assert "alt=media" in str(route.calls.last.request.url)


@respx.mock
async def test_download_uses_export_for_google_native_files() -> None:
    """Google-native documents download through the export endpoint."""
    export_mime, _ = EXPORT_MIME_MAP["application/vnd.google-apps.document"]
    route = respx.get("https://www.googleapis.com/drive/v3/files/f1/export").mock(
        return_value=httpx.Response(200, content=b"DOCXBYTES")
    )
    body = await download_drive_file(
        access_token="at", file_id="f1", export_mime=export_mime, max_bytes=1024
    )
    assert body == b"DOCXBYTES"
    query = parse_qs(urlsplit(str(route.calls.last.request.url)).query)
    assert query["mimeType"] == [export_mime]


@respx.mock
async def test_download_enforces_byte_budget() -> None:
    """Streaming aborts once the accumulated bytes exceed the budget."""
    respx.get("https://www.googleapis.com/drive/v3/files/f1").mock(
        return_value=httpx.Response(200, content=b"x" * 100)
    )
    with pytest.raises(DriveFileTooLargeError):
        await download_drive_file(
            access_token="at", file_id="f1", export_mime=None, max_bytes=99
        )


@respx.mock
async def test_fetch_account_email_reads_about_payload() -> None:
    """The connected account email comes from the Drive about endpoint."""
    respx.get("https://www.googleapis.com/drive/v3/about").mock(
        return_value=httpx.Response(
            200, json={"user": {"emailAddress": "pro@auracles.space"}}
        )
    )
    assert await fetch_drive_account_email("at") == "pro@auracles.space"


@respx.mock
async def test_fetch_account_email_returns_none_on_error_shape() -> None:
    """An unexpected about payload yields None instead of failing connect."""
    respx.get("https://www.googleapis.com/drive/v3/about").mock(
        return_value=httpx.Response(200, json={"error": "nope"})
    )
    assert await fetch_drive_account_email("at") is None
