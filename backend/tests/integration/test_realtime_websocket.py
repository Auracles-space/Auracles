"""Integration tests for the realtime WebSocket gateway."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, Transaction
from app.modules.projects.models import Project, Proposal
from app.modules.realtime import gateway
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_sync


class FakeSubscriptionHandle:
    """Minimal async close handle returned by the subscription test double."""

    async def close(self) -> None:
        """No-op close for WebSocket subscription cleanup."""
        return None


async def never_receive_json() -> dict[str, str]:
    """Simulate a socket that never sends the auth handshake."""
    await asyncio.sleep(3600)
    return {}


class FakeAuthTimeoutWebSocket:
    """Minimal WebSocket double for auth timeout tests."""

    def __init__(self) -> None:
        """Initialise close/send captures."""
        self.closed_code: int | None = None
        self.sent: list[dict[str, str]] = []

    async def send_json(self, payload: dict[str, str]) -> None:
        """Capture sent JSON payloads."""
        self.sent.append(payload)

    async def receive_json(self) -> dict[str, str]:
        """Never return a client message."""
        return await never_receive_json()

    async def close(self, code: int) -> None:
        """Capture the close code."""
        self.closed_code = code


async def dispose_async_engine() -> None:
    """Close async DB transports before sync fixtures continue."""
    await engine.dispose()
    await asyncio.sleep(0.1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure realtime gateway dependent tables exist."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def realtime_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[sessionmaker, list[str]]]:
    """Reset rows and replace Redis subscription with a local test double."""
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    subscribed: list[str] = []

    async def fake_subscribe_channel(channel: str, handler: object) -> object:
        """Record requested channel subscriptions without opening Redis."""
        del handler
        subscribed.append(channel)
        return FakeSubscriptionHandle()

    monkeypatch.setattr(gateway, "subscribe_channel", fake_subscribe_channel)

    def cleanup() -> None:
        """Delete gateway test rows in dependency order."""
        with session_factory() as session:
            session.execute(delete(AuditLog))
            session.execute(delete(Escrow))
            session.execute(delete(Transaction))
            session.execute(delete(Project))
            session.execute(delete(Proposal))
            clear_identity_state_sync(session)
            session.commit()

    cleanup()
    try:
        yield session_factory, subscribed
    finally:
        asyncio.run(dispose_async_engine())
        cleanup()
        sync_engine.dispose()


def create_project_members(session_factory: sessionmaker) -> tuple[UUID, UUID, UUID]:
    """Create accepted Project members plus an outsider user."""
    with session_factory() as session:
        operator = User(
            email=f"ws-operator-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="WS Operator",
            email_verified=True,
            kyc_status="verified",
        )
        contributor = User(
            email=f"ws-contributor-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="WS Contributor",
            email_verified=True,
            kyc_status="verified",
        )
        outsider = User(
            email=f"ws-outsider-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="WS Outsider",
            email_verified=True,
            kyc_status="verified",
        )
        session.add_all([operator, contributor, outsider])
        session.flush()
        session.add_all(
            [
                UserRole(
                    user_id=operator.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                ),
                UserRole(
                    user_id=contributor.id,
                    role="contributor",
                    approved_at=datetime.now(UTC),
                ),
                UserRole(
                    user_id=outsider.id,
                    role="operator",
                    approved_at=datetime.now(UTC),
                ),
            ]
        )
        project = Project(
            operator_id=operator.id,
            title="Realtime Project",
            description="Project used by WebSocket tests.",
            category="operations",
            required_deliverables=[
                {"name": "Guide", "description": "Implementation guide"}
            ],
            budget_min=Decimal("150.00"),
            budget_max=Decimal("150.00"),
            currency="USD",
            status="assigned",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(project)
        session.flush()
        proposal = Proposal(
            project_id=project.id,
            contributor_id=contributor.id,
            scope="I will complete the realtime project work.",
            budget=Decimal("150.00"),
            currency="USD",
            timeline_days=14,
            deliverables=[{"name": "Guide", "description": "Guide"}],
            status="accepted",
            accepted_at=datetime.now(UTC),
        )
        session.add(proposal)
        session.flush()
        project.accepted_proposal_id = proposal.id
        session.commit()
        return operator.id, outsider.id, project.id


def create_suspended_user(session_factory: sessionmaker) -> UUID:
    """Create one suspended Operator account for realtime auth tests."""
    with session_factory() as session:
        user = User(
            email=f"ws-suspended-{uuid4()}@auracles.space",
            password_hash=hash_password("CorrectHorse9"),
            display_name="WS Suspended",
            email_verified=True,
            kyc_status="verified",
            suspended_at=datetime.now(UTC),
        )
        session.add(user)
        session.flush()
        session.add(
            UserRole(
                user_id=user.id,
                role="operator",
                approved_at=datetime.now(UTC),
            )
        )
        session.commit()
        return user.id


def test_websocket_auth_and_project_subscription_authorization(
    migrated_database: None,
    realtime_context: tuple[sessionmaker, list[str]],
) -> None:
    """Gateway authenticates by first message and enforces channel membership."""
    session_factory, subscribed = realtime_context
    operator_id, outsider_id, project_id = create_project_members(session_factory)
    operator_token = create_access_token(operator_id, ["operator"])
    outsider_token = create_access_token(outsider_id, ["operator"])

    with TestClient(app) as client:
        with client.websocket_connect("/v1/ws") as websocket:
            assert websocket.receive_json() == {"type": "auth_required"}
            websocket.send_json({"type": "auth", "token": operator_token})
            auth_ok = websocket.receive_json()
            websocket.send_json({"type": "subscribe", "channel": f"user:{operator_id}"})
            user_subscribed = websocket.receive_json()
            websocket.send_json(
                {"type": "subscribe", "channel": f"project:{project_id}"}
            )
            project_subscribed = websocket.receive_json()

        with client.websocket_connect("/v1/ws") as websocket:
            assert websocket.receive_json() == {"type": "auth_required"}
            websocket.send_json({"type": "auth", "token": outsider_token})
            websocket.receive_json()
            websocket.send_json(
                {"type": "subscribe", "channel": f"project:{project_id}"}
            )
            denied = websocket.receive_json()

    assert auth_ok == {"type": "auth_ok", "user_id": str(operator_id)}
    assert user_subscribed == {
        "type": "subscribed",
        "channel": f"user:{operator_id}",
    }
    assert project_subscribed == {
        "type": "subscribed",
        "channel": f"project:{project_id}",
    }
    assert denied == {
        "type": "error",
        "error_code": "subscription_denied",
        "channel": f"project:{project_id}",
    }
    assert subscribed == [f"user:{operator_id}", f"project:{project_id}"]


def test_websocket_authentication_times_out_without_first_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway closes sockets that do not authenticate within the timeout."""
    websocket = FakeAuthTimeoutWebSocket()
    monkeypatch.setattr(gateway, "AUTH_HANDSHAKE_TIMEOUT_SECONDS", 0.01)

    user = asyncio.run(gateway._authenticate(websocket))

    assert user is None
    assert websocket.sent == [
        {"type": "auth_required"},
        {"type": "error", "error_code": "auth_timeout"},
    ]
    assert websocket.closed_code == 4401


def test_suspended_user_cannot_authenticate_websocket(
    migrated_database: None,
    realtime_context: tuple[sessionmaker, list[str]],
) -> None:
    """Suspended accounts are rejected during realtime auth handshake."""
    session_factory, _ = realtime_context
    suspended_user_id = create_suspended_user(session_factory)
    suspended_token = create_access_token(suspended_user_id, ["operator"])

    with TestClient(app) as client:
        with client.websocket_connect("/v1/ws") as websocket:
            assert websocket.receive_json() == {"type": "auth_required"}
            websocket.send_json({"type": "auth", "token": suspended_token})
            assert websocket.receive_json() == {
                "type": "error",
                "error_code": "invalid_token",
            }
            with pytest.raises(WebSocketDisconnect) as disconnect:
                websocket.receive_json()

    assert disconnect.value.code == 4401


def test_websocket_session_revoked_when_user_suspended_midsession(
    migrated_database: None,
    realtime_context: tuple[sessionmaker, list[str]],
) -> None:
    """A live socket is torn down once the account is suspended mid-session.

    The handshake authorizes off a token snapshot; without per-message
    re-validation a suspended user would keep receiving events until they
    disconnect. The next inbound message must close the socket with 4401.
    """
    session_factory, _ = realtime_context
    operator_id, _, _ = create_project_members(session_factory)
    operator_token = create_access_token(operator_id, ["operator"])

    with TestClient(app) as client:
        with client.websocket_connect("/v1/ws") as websocket:
            assert websocket.receive_json() == {"type": "auth_required"}
            websocket.send_json({"type": "auth", "token": operator_token})
            assert websocket.receive_json() == {
                "type": "auth_ok",
                "user_id": str(operator_id),
            }

            with session_factory() as session:
                user = session.get(User, operator_id)
                assert user is not None
                user.suspended_at = datetime.now(UTC)
                session.commit()

            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {
                "type": "error",
                "error_code": "session_revoked",
            }
            with pytest.raises(WebSocketDisconnect) as disconnect:
                websocket.receive_json()

    assert disconnect.value.code == 4401


def test_websocket_ping_returns_pong(
    migrated_database: None,
    realtime_context: tuple[sessionmaker, list[str]],
) -> None:
    """Authenticated realtime sockets respond to heartbeat pings."""
    session_factory, _ = realtime_context
    operator_id, _, _ = create_project_members(session_factory)
    operator_token = create_access_token(operator_id, ["operator"])

    with TestClient(app) as client:
        with client.websocket_connect("/v1/ws") as websocket:
            assert websocket.receive_json() == {"type": "auth_required"}
            websocket.send_json({"type": "auth", "token": operator_token})
            assert websocket.receive_json() == {
                "type": "auth_ok",
                "user_id": str(operator_id),
            }
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}
