"""Integration tests for audited admin platform configuration endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import PlatformConfig
from app.shared.models.audit_log import AuditLog

DEFAULT_PLATFORM_CONFIG = {
    "commission_rate": "0.15",
    "min_payout_usd": "50",
    "min_payout_ngn": "20000",
    "refund_window_hours": "48",
    "attestation_fee_framework": "250.00",
    "attestation_fee_contributor": "300.00",
    "attestation_fee_operator": "300.00",
    "attestation_fee_credential": "100.00",
    "attestation_cohort_size": "3",
    "attestation_completion_sla_days_framework": "7",
    "attestation_completion_sla_days_contributor": "7",
    "attestation_completion_sla_days_operator": "7",
    "attestation_completion_sla_days_credential": "7",
    "attestation_offer_accept_hours": "48",
    "attestation_dispute_window_days": "14",
    "saved_search_alert_cadence_hours": "24",
    "consent_version_terms_of_service": "1.0",
    "consent_version_privacy_policy": "1.0",
    "account_deletion_grace_days": "14",
    "data_export_expiry_days": "7",
    "reputation_weights_framework": (
        '{"reviews":"0.3500","attestations":"0.3000",'
        '"adoption":"0.3500","completion":"0.0000","recency":"0.0000"}'
    ),
    "reputation_weights_contributor": (
        '{"activity":"0.1500","attestations_received":"0.2000",'
        '"framework_performance":"0.3000","reviews_received":"0.2000",'
        '"verification":"0.1500"}'
    ),
    "reputation_weights_operator": (
        '{"engagement":"0.1500","license_compliance":"0.2500",'
        '"purchase_activity":"0.4000","review_quality":"0.2000"}'
    ),
    "reputation_min_activity_framework": "3",
    "reputation_min_activity_contributor": "1",
    "reputation_min_activity_operator": "1",
    "reputation_prior": "0.5",
    "reputation_prior_strength_k": "5",
    "reputation_decay_halflife_days": "180",
    "reputation_dispute_penalty": "0.2",
}


class FakeRedis:
    """Redis test double for TOTP-sensitive admin config routes."""

    def __init__(self) -> None:
        """Create empty in-memory Redis state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored value or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete stored values and counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


async def reset_admin_config_state() -> None:
    """Restore platform config defaults and remove admin test identities."""
    async with async_session_factory() as session:
        async with session.begin():
            for key, value in DEFAULT_PLATFORM_CONFIG.items():
                config = await session.get(PlatformConfig, key)
                if config is None:
                    session.add(PlatformConfig(key=key, value=value, updated_by=None))
                else:
                    config.value = value
                    config.updated_by = None
            await session.execute(delete(AuditLog))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure Phase 3 financial tables exist for admin config tests."""
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
async def admin_config_context() -> AsyncIterator[FakeRedis]:
    """Reset auth/config state and install Redis test double."""
    fake_redis = FakeRedis()
    await engine.dispose()
    await reset_admin_config_state()

    async def override_redis() -> FakeRedis:
        """Return the Redis test double for dependency injection."""
        return fake_redis

    app.dependency_overrides[get_redis] = override_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_admin_config_state()
        await engine.dispose()


async def create_admin_user(
    *,
    enable_totp: bool = True,
    is_superadmin: bool = True,
) -> tuple[UUID, str | None]:
    """Create an admin user and optional encrypted TOTP secret.

    Defaults to a super-admin because editing platform configuration is reserved
    for the super-admin; pass ``is_superadmin=False`` to test the denial path.
    """
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"config-admin-{uuid4()}@auracles.space",
                password_hash="not-used",
                display_name="Config Admin",
                email_verified=True,
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
                is_superadmin=is_superadmin,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id,
                    role="admin",
                    approved_at=datetime.now(UTC),
                )
            )
        return user.id, secret


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create admin bearer auth headers for tests."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def test_admin_can_read_platform_config(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Admin users can inspect active platform financial configuration."""
    del migrated_database, admin_config_context
    admin_id, _ = await create_admin_user(enable_totp=False)

    response = await client.get(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
    )

    assert response.status_code == 200
    config = {item["key"]: item for item in response.json()["items"]}
    assert config["commission_rate"]["value"] == "0.15"
    assert config["min_payout_usd"]["value"] == "50"
    assert config["refund_window_hours"]["value"] == "48"
    assert config["commission_rate"]["editable"] is True
    assert config["attestation_fee_framework"]["value"] == "250.00"
    assert config["attestation_fee_framework"]["editable"] is True
    assert config["attestation_cohort_size"]["value"] == "3"
    assert config["attestation_cohort_size"]["editable"] is True
    assert config["saved_search_alert_cadence_hours"]["value"] == "24"
    assert config["saved_search_alert_cadence_hours"]["editable"] is True
    assert config["consent_version_terms_of_service"]["value"] == "1.0"
    assert config["consent_version_terms_of_service"]["editable"] is True
    assert config["account_deletion_grace_days"]["value"] == "14"
    assert config["account_deletion_grace_days"]["editable"] is True
    assert config["data_export_expiry_days"]["value"] == "7"
    assert config["data_export_expiry_days"]["editable"] is True
    assert config["reputation_prior"]["value"] == "0.5"
    assert config["reputation_prior"]["editable"] is True
    assert config["reputation_weights_framework"]["editable"] is True
    assert json.loads(config["reputation_weights_framework"]["value"]) == {
        "reviews": "0.3500",
        "attestations": "0.3000",
        "adoption": "0.3500",
        "completion": "0.0000",
        "recency": "0.0000",
    }
    assert config["min_payout_ngn"]["editable"] is False


async def test_non_super_admin_cannot_update_platform_config(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """A plain admin (not super-admin) is forbidden from editing config.

    Enforces that platform configuration changes are reserved for the protected
    super-admin account, while ordinary admins retain read access.
    """
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user(is_superadmin=False)
    assert totp_secret is not None

    forbidden = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Ordinary admin should not be able to do this.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "commission_rate", "value": "0.10"}],
        },
    )
    assert forbidden.status_code == 403

    # Read access is unaffected for ordinary admins.
    readable = await client.get(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
    )
    assert readable.status_code == 200


async def test_admin_updates_editable_config_with_totp_reason_and_audit(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Admin config changes require 2FA and audit each changed key."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    response = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Lower initial launch commission and extend refund window.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [
                {"key": "commission_rate", "value": "0.12"},
                {"key": "refund_window_hours", "value": "72"},
            ],
        },
    )

    async with async_session_factory() as session:
        config_rows = {
            row.key: row
            for row in (
                await session.execute(select(PlatformConfig))
            ).scalars().all()
        }
        audits = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "platform_config_updated")
                .order_by(AuditLog.created_at)
            )
        ).scalars().all()

    assert response.status_code == 200
    response_config = {item["key"]: item for item in response.json()["items"]}
    assert response_config["commission_rate"]["value"] == "0.12"
    assert response_config["refund_window_hours"]["value"] == "72"
    assert config_rows["commission_rate"].value == "0.12"
    assert config_rows["commission_rate"].updated_by == admin_id
    assert config_rows["refund_window_hours"].value == "72"
    assert config_rows["refund_window_hours"].updated_by == admin_id
    assert len(audits) == 2
    assert {audit.metadata_["key"] for audit in audits} == {
        "commission_rate",
        "refund_window_hours",
    }
    assert {
        audit.metadata_["reason"] for audit in audits
    } == {"Lower initial launch commission and extend refund window."}
    assert {
        audit.metadata_["old_value"] for audit in audits
    } == {"0.15", "48"}
    assert {
        audit.metadata_["new_value"] for audit in audits
    } == {"0.12", "72"}


async def test_admin_config_rejects_invalid_2fa_ranges_and_uneditable_keys(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Rejected config changes do not mutate config or create audit rows."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    invalid_2fa = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": "000000",
            "updates": [{"key": "commission_rate", "value": "0.10"}],
        },
    )
    out_of_range = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "commission_rate", "value": "0.75"}],
        },
    )
    uneditable_key = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Paystack is deferred.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "min_payout_ngn", "value": "30000"}],
        },
    )

    async with async_session_factory() as session:
        commission_rate = await session.get(PlatformConfig, "commission_rate")
        min_payout_ngn = await session.get(PlatformConfig, "min_payout_ngn")
        audit_count = len(
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "platform_config_updated"
                    )
                )
            ).scalars().all()
        )

    assert invalid_2fa.status_code == 422
    assert out_of_range.status_code == 422
    assert uneditable_key.status_code == 422
    assert commission_rate is not None
    assert commission_rate.value == "0.15"
    assert min_payout_ngn is not None
    assert min_payout_ngn.value == "20000"
    assert audit_count == 0


async def test_admin_updates_attestation_config_with_range_validation(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Attestation config values are admin-editable only within locked ranges."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    valid_update = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Tune attestation launch defaults.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [
                {"key": "attestation_fee_framework", "value": "275"},
                {"key": "attestation_cohort_size", "value": "5"},
                {"key": "attestation_offer_accept_hours", "value": "72"},
                {"key": "attestation_dispute_window_days", "value": "21"},
            ],
        },
    )
    invalid_fee = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "attestation_fee_credential", "value": "5"}],
        },
    )
    invalid_integer = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "attestation_cohort_size", "value": "11"}],
        },
    )

    async with async_session_factory() as session:
        config_rows = {
            row.key: row.value
            for row in (
                await session.execute(select(PlatformConfig))
            ).scalars().all()
        }

    assert valid_update.status_code == 200
    response_config = {item["key"]: item for item in valid_update.json()["items"]}
    assert response_config["attestation_fee_framework"]["value"] == "275"
    assert response_config["attestation_cohort_size"]["value"] == "5"
    assert response_config["attestation_offer_accept_hours"]["value"] == "72"
    assert response_config["attestation_dispute_window_days"]["value"] == "21"
    assert config_rows["attestation_fee_framework"] == "275"
    assert config_rows["attestation_cohort_size"] == "5"
    assert invalid_fee.status_code == 422
    assert invalid_integer.status_code == 422


async def test_admin_updates_saved_search_alert_cadence_with_range_validation(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Saved-search alert cadence is admin-editable within the 1-168h range."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    valid_update = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Run saved search alerts every six hours.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "saved_search_alert_cadence_hours", "value": "6"}],
        },
    )
    invalid_low = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "saved_search_alert_cadence_hours", "value": "0"}],
        },
    )
    invalid_high = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "saved_search_alert_cadence_hours", "value": "169"}],
        },
    )

    async with async_session_factory() as session:
        cadence = await session.get(
            PlatformConfig,
            "saved_search_alert_cadence_hours",
        )

    assert valid_update.status_code == 200
    response_config = {item["key"]: item for item in valid_update.json()["items"]}
    assert response_config["saved_search_alert_cadence_hours"]["value"] == "6"
    assert cadence is not None
    assert cadence.value == "6"
    assert invalid_low.status_code == 422
    assert invalid_high.status_code == 422


async def test_admin_updates_gdpr_config_with_range_validation(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """GDPR consent and retention knobs are admin-editable within safe ranges."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    valid_update = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Update legal versions and deletion/export windows.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [
                {"key": "consent_version_terms_of_service", "value": "2026.06"},
                {"key": "consent_version_privacy_policy", "value": "2026.06"},
                {"key": "account_deletion_grace_days", "value": "21"},
                {"key": "data_export_expiry_days", "value": "10"},
            ],
        },
    )
    invalid_grace = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "account_deletion_grace_days", "value": "31"}],
        },
    )
    invalid_expiry = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "data_export_expiry_days", "value": "0"}],
        },
    )
    invalid_version = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "consent_version_privacy_policy", "value": " "}],
        },
    )

    async with async_session_factory() as session:
        config_rows = {
            row.key: row.value
            for row in (
                await session.execute(select(PlatformConfig))
            ).scalars().all()
        }

    assert valid_update.status_code == 200
    response_config = {item["key"]: item for item in valid_update.json()["items"]}
    assert response_config["consent_version_terms_of_service"]["value"] == "2026.06"
    assert response_config["consent_version_privacy_policy"]["value"] == "2026.06"
    assert response_config["account_deletion_grace_days"]["value"] == "21"
    assert response_config["data_export_expiry_days"]["value"] == "10"
    assert config_rows["consent_version_terms_of_service"] == "2026.06"
    assert config_rows["account_deletion_grace_days"] == "21"
    assert invalid_grace.status_code == 422
    assert invalid_expiry.status_code == 422
    assert invalid_version.status_code == 422


async def test_admin_updates_reputation_config_with_shape_and_range_validation(
    client: AsyncClient,
    migrated_database: None,
    admin_config_context: FakeRedis,
) -> None:
    """Reputation config updates enforce valid factor shapes and scalar bounds."""
    del migrated_database, admin_config_context
    admin_id, totp_secret = await create_admin_user()
    assert totp_secret is not None

    valid_update = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Tune reputation scoring launch defaults.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [
                {
                    "key": "reputation_weights_framework",
                    "value": (
                        '{"reviews":"0.4000","attestations":"0.2500",'
                        '"adoption":"0.3500","completion":"0.0000","recency":"0.0000"}'
                    ),
                },
                {"key": "reputation_prior", "value": "0.65"},
                {"key": "reputation_min_activity_framework", "value": "4"},
                {"key": "reputation_prior_strength_k", "value": "8.5"},
                {"key": "reputation_dispute_penalty", "value": "0.15"},
            ],
        },
    )
    invalid_weights = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [
                {
                    "key": "reputation_weights_framework",
                    "value": '{"reviews":"0.50","attestations":"0.50"}',
                }
            ],
        },
    )
    invalid_prior = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Should not pass.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [{"key": "reputation_prior", "value": "1.2"}],
        },
    )
    invalid_decay = await client.patch(
        "/v1/admin/config",
        headers=auth_headers(admin_id),
        json={
            "reason": "Decay is not wired into the engine yet.",
            "totp_code": pyotp.TOTP(totp_secret).now(),
            "updates": [
                {"key": "reputation_decay_halflife_days", "value": "365"}
            ],
        },
    )

    async with async_session_factory() as session:
        config_rows = {
            row.key: row.value
            for row in (
                await session.execute(select(PlatformConfig))
            ).scalars().all()
        }

    assert valid_update.status_code == 200
    response_config = {item["key"]: item for item in valid_update.json()["items"]}
    assert json.loads(response_config["reputation_weights_framework"]["value"]) == {
        "adoption": "0.3500",
        "attestations": "0.2500",
        "completion": "0.0000",
        "recency": "0.0000",
        "reviews": "0.4000",
    }
    assert response_config["reputation_prior"]["value"] == "0.65"
    assert response_config["reputation_min_activity_framework"]["value"] == "4"
    assert response_config["reputation_prior_strength_k"]["value"] == "8.5"
    assert response_config["reputation_dispute_penalty"]["value"] == "0.15"
    assert config_rows["reputation_prior"] == "0.65"
    assert invalid_weights.status_code == 422
    assert invalid_prior.status_code == 422
    assert invalid_decay.status_code == 422
