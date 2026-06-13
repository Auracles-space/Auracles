"""Integration tests for authenticated notification preference settings.

These tests exercise the public `/v1/settings/notification-preferences`
endpoints so the settings surface, worker gates, and frontend matrix all share
one stable contract.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.notifications.models import NotificationPreference
from app.shared.models.audit_log import AuditLog


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the latest settings and notification tables exist for the tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def notification_preferences_context() -> AsyncIterator[None]:
    """Reset user-owned settings state before each notification test."""
    await engine.dispose()
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(NotificationPreference))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()

    try:
        yield
    finally:
        await engine.dispose()


async def _create_user(
    *,
    email: str,
    roles: list[str],
) -> UUID:
    """Create one verified user with the provided application roles."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name="Preference User",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add_all(
                [UserRole(user_id=user.id, role=role) for role in roles]
            )
        return user.id


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for one authenticated test user."""
    return {
        "Authorization": (
            f"Bearer {create_access_token(user_id=user_id, roles=roles)}"
        )
    }


async def test_get_notification_preferences_returns_effective_grouped_matrix(
    client: AsyncClient,
    migrated_database: None,
    notification_preferences_context: None,
) -> None:
    """GET returns grouped effective preferences with locked critical rows."""
    current_user_id = await _create_user(
        email="owner@auracles.space",
        roles=["operator"],
    )
    other_user_id = await _create_user(
        email="other@auracles.space",
        roles=["operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                NotificationPreference(
                    user_id=current_user_id,
                    notification_type="saved_search_alert",
                    category="discovery",
                    channel="email",
                    enabled=False,
                )
            )
            session.add(
                NotificationPreference(
                    user_id=other_user_id,
                    notification_type="proposal_submitted",
                    category="project",
                    channel="in_app",
                    enabled=False,
                )
            )

    response = await client.get(
        "/v1/settings/notification-preferences",
        headers=_auth_headers(current_user_id, ["operator"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert [category["category"] for category in body["categories"]] == [
        "project",
        "attestation",
        "financial",
        "discovery",
        "account",
    ]

    discovery_category = next(
        category
        for category in body["categories"]
        if category["category"] == "discovery"
    )
    saved_search = next(
        item
        for item in discovery_category["preferences"]
        if item["notification_type"] == "saved_search_alert"
    )
    assert saved_search["label"] == "Saved Search Alert"
    assert saved_search["description"] == "Receive saved search alert updates."
    assert saved_search["channels"] == [
        {"channel": "email", "enabled": False, "locked": False},
        {"channel": "in_app", "enabled": True, "locked": False},
    ]

    financial_category = next(
        category
        for category in body["categories"]
        if category["category"] == "financial"
    )
    critical_row = next(
        item
        for item in financial_category["preferences"]
        if item["notification_type"] == "dispute_resolved_release"
    )
    assert critical_row["channels"] == [
        {"channel": "email", "enabled": True, "locked": True},
        {"channel": "in_app", "enabled": True, "locked": True},
    ]

    project_category = next(
        category
        for category in body["categories"]
        if category["category"] == "project"
    )
    proposal_submitted = next(
        item
        for item in project_category["preferences"]
        if item["notification_type"] == "proposal_submitted"
    )
    assert proposal_submitted["channels"] == [
        {"channel": "email", "enabled": True, "locked": False},
        {"channel": "in_app", "enabled": True, "locked": False},
    ]


async def test_patch_notification_preferences_upserts_and_audits(
    client: AsyncClient,
    migrated_database: None,
    notification_preferences_context: None,
) -> None:
    """PATCH stores per-channel overrides and returns the refreshed matrix."""
    current_user_id = await _create_user(
        email="patch-owner@auracles.space",
        roles=["operator"],
    )

    response = await client.patch(
        "/v1/settings/notification-preferences",
        headers=_auth_headers(current_user_id, ["operator"]),
        json={
            "updates": [
                {
                    "notification_type": "saved_search_alert",
                    "channel": "email",
                    "enabled": False,
                },
                {
                    "notification_type": "proposal_submitted",
                    "channel": "in_app",
                    "enabled": False,
                },
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    discovery_category = next(
        category
        for category in body["categories"]
        if category["category"] == "discovery"
    )
    saved_search = next(
        item
        for item in discovery_category["preferences"]
        if item["notification_type"] == "saved_search_alert"
    )
    assert saved_search["channels"] == [
        {"channel": "email", "enabled": False, "locked": False},
        {"channel": "in_app", "enabled": True, "locked": False},
    ]

    project_category = next(
        category
        for category in body["categories"]
        if category["category"] == "project"
    )
    proposal_submitted = next(
        item
        for item in project_category["preferences"]
        if item["notification_type"] == "proposal_submitted"
    )
    assert proposal_submitted["channels"] == [
        {"channel": "email", "enabled": True, "locked": False},
        {"channel": "in_app", "enabled": False, "locked": False},
    ]

    async with async_session_factory() as session:
        stored = (
            await session.execute(
                select(
                    NotificationPreference.notification_type,
                    NotificationPreference.channel,
                    NotificationPreference.enabled,
                    NotificationPreference.category,
                )
            )
        ).all()
        audit_log = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "notification_preferences_updated"
            )
        )

    assert set(stored) == {
        ("saved_search_alert", "email", False, "discovery"),
        ("proposal_submitted", "in_app", False, "project"),
    }
    assert audit_log is not None
    assert audit_log.actor_id == current_user_id
    assert audit_log.metadata_ == {
        "updated_count": 2,
        "keys": [
            "saved_search_alert:email",
            "proposal_submitted:in_app",
        ],
    }


async def test_patch_notification_preferences_rejects_disabling_critical_rows(
    client: AsyncClient,
    migrated_database: None,
    notification_preferences_context: None,
) -> None:
    """PATCH must reject attempts to disable critical notification types."""
    current_user_id = await _create_user(
        email="critical-owner@auracles.space",
        roles=["operator"],
    )

    response = await client.patch(
        "/v1/settings/notification-preferences",
        headers=_auth_headers(current_user_id, ["operator"]),
        json={
            "updates": [
                {
                    "notification_type": "dispute_resolved_release",
                    "channel": "email",
                    "enabled": False,
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Critical notification preferences cannot be disabled."
    )


async def test_patch_rejects_disabling_money_state_critical_rows(
    client: AsyncClient,
    migrated_database: None,
    notification_preferences_context: None,
) -> None:
    """PATCH must reject disabling escrow and payout state notifications."""
    current_user_id = await _create_user(
        email="money-critical-owner@auracles.space",
        roles=["contributor"],
    )

    response = await client.patch(
        "/v1/settings/notification-preferences",
        headers=_auth_headers(current_user_id, ["contributor"]),
        json={
            "updates": [
                {
                    "notification_type": "deliverable_approved",
                    "channel": "email",
                    "enabled": False,
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Critical notification preferences cannot be disabled."
    )
