"""Unit tests for the verified organization logo upload flow.

The org logo is set exclusively through a two-step verified upload (request a
presigned target, then confirm the uploaded object). These tests lock the type
and size validation, the org-namespaced key scheme, the confirm-time ownership
and existence checks, and the removal of the old free-string ``logo_key``
setter from the profile update path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.integrations import s3
from app.main import app
from app.modules.auth.models import User
from app.modules.organizations import service
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations.models import Organization, OrgMember
from app.modules.organizations.schemas import (
    LogoConfirmRequest,
    LogoUploadUrlRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org-logo unit tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_logo_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset org rows around each logo-upload test."""
    del migrated_database
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_owner_context() -> tuple[OrgContext, User, Organization]:
    """Create an org with an owner and return the owner's OrgContext."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"logo-owner-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Logo Owner",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            org = Organization(
                slug=f"logo-org-{uuid4().hex[:8]}",
                name="Logo Org",
                country="GB",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role="owner")
            session.add(member)
            await session.flush()
            await session.refresh(user)
            await session.refresh(org)
            await session.refresh(member)
            return OrgContext(org=org, member=member, user=user), user, org


@pytest.mark.asyncio
async def test_request_logo_upload_url_rejects_non_image(
    org_logo_state: None,
) -> None:
    """A non-image MIME type is rejected with 415 before any target is minted."""
    context, _user, _org = await _create_owner_context()
    with pytest.raises(Exception) as exc_info:
        service.request_org_logo_upload_url(
            context=context,
            payload=LogoUploadUrlRequest(
                mime_type="application/pdf", file_size=1024
            ),
        )
    assert getattr(exc_info.value, "status_code", None) == 415


@pytest.mark.asyncio
async def test_request_logo_upload_url_rejects_oversize(
    org_logo_state: None,
) -> None:
    """A declared size above the cap is rejected with 413."""
    context, _user, _org = await _create_owner_context()
    with pytest.raises(Exception) as exc_info:
        service.request_org_logo_upload_url(
            context=context,
            payload=LogoUploadUrlRequest(
                mime_type="image/png", file_size=service.LOGO_MAX_SIZE + 1
            ),
        )
    assert getattr(exc_info.value, "status_code", None) == 413


@pytest.mark.asyncio
async def test_request_logo_upload_url_returns_org_namespaced_target(
    org_logo_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid request mints a presigned target keyed under the org's namespace."""
    context, _user, org = await _create_owner_context()
    captured: dict[str, object] = {}

    def _fake_presign(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"url": "https://s3.example/upload", "fields": {"key": "v"}}

    monkeypatch.setattr(s3.storage, "presigned_post", _fake_presign)

    result = service.request_org_logo_upload_url(
        context=context,
        payload=LogoUploadUrlRequest(mime_type="image/png", file_size=2048),
    )

    assert result.file_key.startswith(f"org-logos/{org.id}/")
    assert result.file_key.endswith(".png")
    assert result.max_size == service.LOGO_MAX_SIZE
    assert result.expires_in == service.LOGO_UPLOAD_URL_TTL_SECONDS
    assert result.upload_url == "https://s3.example/upload"
    # Uploads land in the (public) avatars bucket, size-capped by S3 policy.
    assert captured["bucket"] == app.state.settings.s3_avatars_bucket
    assert captured["max_size"] == service.LOGO_MAX_SIZE


@pytest.mark.asyncio
async def test_confirm_logo_upload_rejects_key_outside_org_namespace(
    org_logo_state: None,
) -> None:
    """A key namespaced under a different org id is rejected with 403."""
    context, _user, _org = await _create_owner_context()
    foreign_key = f"org-logos/{uuid4()}/{uuid4()}.png"
    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await service.confirm_org_logo_upload(
                session,
                context=context,
                payload=LogoConfirmRequest(file_key=foreign_key),
            )
    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_confirm_logo_upload_rejects_missing_object(
    org_logo_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirm for a key with no uploaded object is rejected with 409."""
    context, _user, org = await _create_owner_context()
    monkeypatch.setattr(
        s3.storage, "object_exists", lambda bucket, key: False
    )
    key = f"org-logos/{org.id}/{uuid4()}.png"
    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await service.confirm_org_logo_upload(
                session,
                context=context,
                payload=LogoConfirmRequest(file_key=key),
            )
    assert getattr(exc_info.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_confirm_logo_upload_persists_logo_key(
    org_logo_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed, existing upload persists logo_key on the organization."""
    context, _user, org = await _create_owner_context()
    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: True)
    key = f"org-logos/{org.id}/{uuid4()}.png"

    async with async_session_factory() as session:
        response = await service.confirm_org_logo_upload(
            session,
            context=context,
            payload=LogoConfirmRequest(file_key=key),
        )

    assert response.logo_key == key
    async with async_session_factory() as session:
        stored = await session.get(Organization, org.id)
        assert stored is not None
        assert stored.logo_key == key


def _expected_avatars_public_url(key: str) -> str:
    """Build the public URL the avatars bucket serves ``key`` at (test-local)."""
    settings = app.state.settings
    bucket = settings.s3_avatars_bucket
    if settings.aws_endpoint_url is not None:
        return f"{settings.aws_endpoint_url.rstrip('/')}/{bucket}/{key}"
    return f"https://{bucket}.s3.{settings.aws_default_region}.amazonaws.com/{key}"


@pytest.mark.asyncio
async def test_confirm_logo_upload_returns_public_logo_url(
    org_logo_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The confirm response exposes a resolved public ``logo_url`` for the key.

    Clients cannot serve the raw ``logo_key``; the response must carry the
    deterministic public URL so the logo renders without client-side S3 logic.
    """
    context, _user, org = await _create_owner_context()
    monkeypatch.setattr(s3.storage, "object_exists", lambda bucket, key: True)
    key = f"org-logos/{org.id}/{uuid4()}.png"

    async with async_session_factory() as session:
        response = await service.confirm_org_logo_upload(
            session,
            context=context,
            payload=LogoConfirmRequest(file_key=key),
        )

    assert response.logo_url == _expected_avatars_public_url(key)


def test_organization_response_logo_url_is_none_without_key() -> None:
    """An org with no ``logo_key`` reports ``logo_url`` as ``None``."""
    response = OrganizationResponse.model_validate(
        {
            "id": uuid4(),
            "slug": "no-logo-org",
            "name": "No Logo Org",
            "logo_key": None,
            "country": "GB",
            "website": None,
            "description": None,
            "created_at": __import__("datetime").datetime(2026, 7, 13),
        }
    )
    assert response.logo_url is None


@pytest.mark.asyncio
async def test_update_organization_ignores_logo_key(
    org_logo_state: None,
) -> None:
    """The profile update path can no longer set logo_key (backdoor closed)."""
    context, _user, org = await _create_owner_context()
    # logo_key is not a field on OrganizationUpdateRequest; if supplied it is
    # ignored, so update must never write it.
    payload = OrganizationUpdateRequest.model_validate(
        {"name": "Renamed Org", "logo_key": "org-logos/attacker/evil.png"}
    )
    async with async_session_factory() as session:
        response = await service.update_organization(
            session, context=context, payload=payload
        )

    assert response.name == "Renamed Org"
    assert response.logo_key is None
