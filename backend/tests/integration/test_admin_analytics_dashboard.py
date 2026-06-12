"""Integration tests for admin analytics dashboard and snapshot behavior.

These tests exercise the public admin HTTP contract for current-state
analytics and the daily snapshot task that backs dashboard trend rows. They
verify GMV aggregation, by-source breakdowns, string-safe money output, UTC
snapshot boundaries, and rerun idempotency.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from freezegun import freeze_time
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.admin.models import AnalyticsDailySnapshot
from app.modules.attestation.models import Attestation, AttestationDispute
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework
from app.modules.projects.models import Dispute, Milestone, Project
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import admin_beat


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create bearer auth headers for an admin user."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    roles: list[str],
    created_at: datetime,
) -> User:
    """Create a verified user with approved roles for analytics tests."""
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorse9"),
        display_name=email.split("@")[0],
        email_verified=True,
        kyc_status="verified",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    await session.flush()
    for role in roles:
        session.add(
            UserRole(
                user_id=user.id,
                role=role,
                approved_at=created_at,
                created_at=created_at,
            )
        )
    await session.flush()
    return user


async def _create_transaction(
    session: AsyncSession,
    *,
    payer_id: UUID,
    payee_id: UUID,
    amount: Decimal,
    transaction_type: str,
    status: str,
    ref_type: str,
    created_at: datetime,
    currency: str = "USD",
) -> Transaction:
    """Create a transaction row with explicit timing for GMV aggregation tests."""
    transaction = Transaction(
        payer_id=payer_id,
        payee_id=payee_id,
        amount=amount,
        currency=currency,
        platform_commission=Decimal("0.00"),
        net_amount=amount,
        transaction_type=transaction_type,
        status=status,
        provider="stripe",
        provider_ref=f"pi_admin_dashboard_{uuid4().hex[:12]}",
        ref_id=uuid4(),
        ref_type=ref_type,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(transaction)
    await session.flush()
    return transaction


async def _cleanup_admin_dashboard_state() -> None:
    """Delete analytics test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AnalyticsDailySnapshot))
        await session.execute(delete(AuditLog))
        await session.execute(delete(AttestationDispute))
        await session.execute(delete(Attestation))
        await session.execute(delete(Dispute))
        await session.execute(delete(Milestone))
        await session.execute(delete(Project))
        await session.execute(delete(Transaction))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database schema is current for admin analytics tests."""
    backend_dir = Path(__file__).resolve().parents[2]
    sync_engine = create_engine(app.state.settings.sync_database_url)
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(config, "head")
    try:
        yield
    finally:
        command.upgrade(config, "head")
        sync_engine.dispose()


async def test_admin_dashboard_reports_gmv_windows_and_by_source_strings(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """Dashboard GMV must include only completed USD marketplace revenue."""
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup_admin_dashboard_state()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                admin = await _create_user(
                    session,
                    email=f"admin-{uuid4()}@auracles.space",
                    roles=["admin"],
                    created_at=now - timedelta(days=60),
                )
                operator = await _create_user(
                    session,
                    email=f"operator-{uuid4()}@auracles.space",
                    roles=["operator"],
                    created_at=now - timedelta(days=12),
                )
                contributor = await _create_user(
                    session,
                    email=f"contributor-{uuid4()}@auracles.space",
                    roles=["contributor"],
                    created_at=now - timedelta(days=12),
                )

                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("100.00"),
                    transaction_type="purchase",
                    status="completed",
                    ref_type="framework",
                    created_at=now - timedelta(hours=3),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("200.00"),
                    transaction_type="purchase",
                    status="completed",
                    ref_type="collection",
                    created_at=now - timedelta(hours=2),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("300.00"),
                    transaction_type="milestone",
                    status="completed",
                    ref_type="project_milestone",
                    created_at=now - timedelta(days=2),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("400.00"),
                    transaction_type="attestation_fee",
                    status="completed",
                    ref_type="attestation",
                    created_at=now - timedelta(days=5),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("50.00"),
                    transaction_type="purchase",
                    status="completed",
                    ref_type="framework",
                    created_at=now - timedelta(days=20),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("999.00"),
                    transaction_type="purchase",
                    status="failed",
                    ref_type="framework",
                    created_at=now - timedelta(hours=1),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("888.00"),
                    transaction_type="purchase",
                    status="refunded",
                    ref_type="framework",
                    created_at=now - timedelta(days=1),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("777.00"),
                    transaction_type="refund",
                    status="completed",
                    ref_type="framework",
                    created_at=now - timedelta(days=1),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("666.00"),
                    transaction_type="purchase",
                    status="completed",
                    ref_type="framework",
                    currency="NGN",
                    created_at=now - timedelta(days=1),
                )

            response = await client.get(
                "/v1/admin/analytics/dashboard",
                headers=auth_headers(admin.id),
            )
    finally:
        await _cleanup_admin_dashboard_state()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["trend"] == []
    assert body["gmv"]["today_total"] == "300.00"
    assert body["gmv"]["last_7_days_total"] == "1000.00"
    assert body["gmv"]["last_30_days_total"] == "1050.00"
    assert body["gmv"]["today_by_source"] == {
        "framework_purchase": "100.00",
        "collection_purchase": "200.00",
        "project_milestone": "0.00",
        "attestation_fee": "0.00",
    }
    assert body["gmv"]["last_7_days_by_source"] == {
        "framework_purchase": "100.00",
        "collection_purchase": "200.00",
        "project_milestone": "300.00",
        "attestation_fee": "400.00",
    }
    assert body["gmv"]["last_30_days_by_source"] == {
        "framework_purchase": "150.00",
        "collection_purchase": "200.00",
        "project_milestone": "300.00",
        "attestation_fee": "400.00",
    }


async def test_admin_dashboard_reports_current_state_counts(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """Dashboard current-state counts must reflect audit, content, and dispute state."""
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup_admin_dashboard_state()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                admin = await _create_user(
                    session,
                    email=f"admin-counts-{uuid4()}@auracles.space",
                    roles=["admin"],
                    created_at=now - timedelta(days=60),
                )
                operator = await _create_user(
                    session,
                    email=f"operator-counts-{uuid4()}@auracles.space",
                    roles=["operator"],
                    created_at=now - timedelta(hours=2),
                )
                contributor = await _create_user(
                    session,
                    email=f"contributor-counts-{uuid4()}@auracles.space",
                    roles=["contributor"],
                    created_at=now - timedelta(days=5),
                )
                attestor = await _create_user(
                    session,
                    email=f"attestor-counts-{uuid4()}@auracles.space",
                    roles=["attestor"],
                    created_at=now - timedelta(days=20),
                )
                await _create_user(
                    session,
                    email=f"stale-counts-{uuid4()}@auracles.space",
                    roles=["operator"],
                    created_at=now - timedelta(days=40),
                )

                session.add_all(
                    [
                        Framework(
                            contributor_id=contributor.id,
                            title="Fresh Published",
                            description="Fresh dashboard fixture.",
                            status="published",
                            category="operations",
                            sector="technology",
                            industry="software",
                            business_function="operations",
                            tags=["fresh"],
                            tags_text="fresh",
                            price=Decimal("100.00"),
                            currency="USD",
                            license_types=["single_user"],
                            created_at=now - timedelta(hours=3),
                            updated_at=now - timedelta(hours=3),
                            published_at=now - timedelta(hours=3),
                        ),
                        Framework(
                            contributor_id=contributor.id,
                            title="Week Published",
                            description="Week dashboard fixture.",
                            status="published",
                            category="operations",
                            sector="technology",
                            industry="software",
                            business_function="operations",
                            tags=["week"],
                            tags_text="week",
                            price=Decimal("120.00"),
                            currency="USD",
                            license_types=["single_user"],
                            created_at=now - timedelta(days=4),
                            updated_at=now - timedelta(days=4),
                            published_at=now - timedelta(days=4),
                        ),
                        Framework(
                            contributor_id=contributor.id,
                            title="Month Published",
                            description="Month dashboard fixture.",
                            status="published",
                            category="operations",
                            sector="technology",
                            industry="software",
                            business_function="operations",
                            tags=["month"],
                            tags_text="month",
                            price=Decimal("140.00"),
                            currency="USD",
                            license_types=["single_user"],
                            created_at=now - timedelta(days=20),
                            updated_at=now - timedelta(days=20),
                            published_at=now - timedelta(days=20),
                        ),
                        Framework(
                            contributor_id=contributor.id,
                            title="Draft Framework",
                            description="Excluded dashboard fixture.",
                            status="draft",
                            category="operations",
                            sector="technology",
                            industry="software",
                            business_function="operations",
                            tags=["draft"],
                            tags_text="draft",
                            price=Decimal("160.00"),
                            currency="USD",
                            license_types=["single_user"],
                            created_at=now - timedelta(hours=1),
                            updated_at=now - timedelta(hours=1),
                        ),
                    ]
                )
                await session.flush()

                recent_attestation = Attestation(
                    target_type="framework",
                    target_id=uuid4(),
                    requestor_id=operator.id,
                    attestor_id=attestor.id,
                    status="report_submitted",
                    outcome="approved",
                    requested_specializations=["risk"],
                    requested_jurisdictions=["us"],
                    fee_amount=Decimal("250.00"),
                    currency="USD",
                    issued_at=now - timedelta(hours=4),
                    created_at=now - timedelta(hours=4),
                    updated_at=now - timedelta(hours=4),
                )
                week_attestation = Attestation(
                    target_type="framework",
                    target_id=uuid4(),
                    requestor_id=operator.id,
                    attestor_id=attestor.id,
                    status="closed",
                    outcome="conditional",
                    requested_specializations=["ops"],
                    requested_jurisdictions=["uk"],
                    fee_amount=Decimal("260.00"),
                    currency="USD",
                    issued_at=now - timedelta(days=5),
                    closed_at=now - timedelta(days=5),
                    created_at=now - timedelta(days=5),
                    updated_at=now - timedelta(days=5),
                )
                month_attestation = Attestation(
                    target_type="framework",
                    target_id=uuid4(),
                    requestor_id=operator.id,
                    attestor_id=attestor.id,
                    status="closed",
                    outcome="approved",
                    requested_specializations=["finance"],
                    requested_jurisdictions=["ca"],
                    fee_amount=Decimal("270.00"),
                    currency="USD",
                    issued_at=now - timedelta(days=20),
                    closed_at=now - timedelta(days=20),
                    created_at=now - timedelta(days=20),
                    updated_at=now - timedelta(days=20),
                )
                excluded_attestation = Attestation(
                    target_type="framework",
                    target_id=uuid4(),
                    requestor_id=operator.id,
                    attestor_id=attestor.id,
                    status="pending_fee",
                    outcome=None,
                    requested_specializations=["excluded"],
                    requested_jurisdictions=["us"],
                    fee_amount=Decimal("280.00"),
                    currency="USD",
                    created_at=now - timedelta(hours=1),
                    updated_at=now - timedelta(hours=1),
                )
                session.add_all(
                    [
                        recent_attestation,
                        week_attestation,
                        month_attestation,
                        excluded_attestation,
                    ]
                )
                await session.flush()

                project = Project(
                    operator_id=operator.id,
                    title="Admin Dashboard Project",
                    description="Project dispute fixture.",
                    category="operations",
                    required_deliverables=[{"name": "Playbook"}],
                    budget_min=Decimal("1000.00"),
                    budget_max=Decimal("1500.00"),
                    currency="USD",
                    status="disputed",
                    milestone_plan_status="draft",
                    expires_at=now + timedelta(days=7),
                    created_at=now - timedelta(days=3),
                    updated_at=now - timedelta(days=3),
                )
                session.add(project)
                await session.flush()
                milestone = Milestone(
                    project_id=project.id,
                    sequence=1,
                    name="Milestone 1",
                    description="Milestone dispute fixture.",
                    budget=Decimal("1000.00"),
                    currency="USD",
                    status="disputed",
                    created_at=now - timedelta(days=3),
                )
                session.add(milestone)
                await session.flush()
                session.add_all(
                    [
                        Dispute(
                            project_id=project.id,
                            milestone_id=milestone.id,
                            raised_by=operator.id,
                            reason="Need admin review.",
                            status="open",
                            created_at=now - timedelta(days=2),
                        ),
                        Dispute(
                            project_id=project.id,
                            milestone_id=milestone.id,
                            raised_by=contributor.id,
                            reason="Already resolved.",
                            status="resolved",
                            resolution_type="refund",
                            created_at=now - timedelta(days=1),
                        ),
                        AttestationDispute(
                            attestation_id=recent_attestation.id,
                            raised_by=operator.id,
                            reason="Attestation under review.",
                            status="under_review",
                            created_at=now - timedelta(hours=6),
                        ),
                        AttestationDispute(
                            attestation_id=week_attestation.id,
                            raised_by=operator.id,
                            reason="Closed dispute.",
                            status="resolved",
                            resolution_type="release",
                            created_at=now - timedelta(days=1),
                        ),
                    ]
                )
                session.add_all(
                    [
                        AuditLog(
                            actor_id=operator.id,
                            action="operator_seen",
                            target_type="session",
                            target_id=None,
                            metadata_={},
                            created_at=now - timedelta(hours=3),
                        ),
                        AuditLog(
                            actor_id=operator.id,
                            action="operator_seen_again",
                            target_type="session",
                            target_id=None,
                            metadata_={},
                            created_at=now - timedelta(hours=2),
                        ),
                        AuditLog(
                            actor_id=contributor.id,
                            action="contributor_seen",
                            target_type="session",
                            target_id=None,
                            metadata_={},
                            created_at=now - timedelta(days=6),
                        ),
                        AuditLog(
                            actor_id=attestor.id,
                            action="attestor_seen",
                            target_type="session",
                            target_id=None,
                            metadata_={},
                            created_at=now - timedelta(days=20),
                        ),
                        AuditLog(
                            actor_id=None,
                            action="anonymous_event",
                            target_type="session",
                            target_id=None,
                            metadata_={},
                            created_at=now - timedelta(hours=1),
                        ),
                    ]
                )

            response = await client.get(
                "/v1/admin/analytics/dashboard",
                headers=auth_headers(admin.id),
            )
    finally:
        await _cleanup_admin_dashboard_state()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["active_users"] == {
        "last_24_hours": 1,
        "last_7_days": 2,
        "last_30_days": 3,
    }
    assert body["new_registrations"] == {
        "last_24_hours": 1,
        "last_7_days": 2,
        "last_30_days": 3,
    }
    assert body["frameworks_published"] == {
        "total": 3,
        "last_24_hours": 1,
        "last_7_days": 2,
        "last_30_days": 3,
    }
    assert body["attestations_issued"] == {
        "last_24_hours": 1,
        "last_7_days": 2,
        "last_30_days": 3,
    }
    assert body["disputes_open"] == {
        "total": 2,
        "projects": 1,
        "attestations": 1,
    }
    assert body["trend"] == []


async def test_daily_snapshot_captures_prior_utc_day_and_dashboard_trend(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """Snapshot Beat must freeze the prior UTC day and expose ordered trend rows."""
    del migrated_database
    frozen_now = "2026-06-12 00:10:00+00:00"
    target_day = datetime(2026, 6, 11, 0, 0, tzinfo=UTC)
    next_day = datetime(2026, 6, 12, 0, 0, tzinfo=UTC)
    await engine.dispose()
    await _cleanup_admin_dashboard_state()
    try:
        with freeze_time(frozen_now):
            async with async_session_factory() as session:
                async with session.begin():
                    admin = await _create_user(
                        session,
                        email=f"admin-snapshot-{uuid4()}@auracles.space",
                        roles=["admin"],
                        created_at=target_day - timedelta(days=30),
                    )
                    operator = await _create_user(
                        session,
                        email=f"operator-snapshot-{uuid4()}@auracles.space",
                        roles=["operator"],
                        created_at=target_day + timedelta(hours=1),
                    )
                    contributor = await _create_user(
                        session,
                        email=f"contributor-snapshot-{uuid4()}@auracles.space",
                        roles=["contributor"],
                        created_at=target_day + timedelta(hours=2),
                    )
                    attestor = await _create_user(
                        session,
                        email=f"attestor-snapshot-{uuid4()}@auracles.space",
                        roles=["attestor"],
                        created_at=target_day - timedelta(days=10),
                    )
                    late_user = await _create_user(
                        session,
                        email=f"late-user-snapshot-{uuid4()}@auracles.space",
                        roles=["operator"],
                        created_at=next_day + timedelta(minutes=1),
                    )

                    session.add(
                        AnalyticsDailySnapshot(
                            snapshot_date=(target_day - timedelta(days=1)).date(),
                            gmv_total=Decimal("80.00"),
                            gmv_by_source={"framework_purchase": "80.00"},
                            active_users=1,
                            new_registrations=1,
                            frameworks_published=1,
                            attestations_issued=0,
                            disputes_open=0,
                            computed_at=target_day - timedelta(minutes=5),
                        )
                    )

                    framework = Framework(
                        contributor_id=contributor.id,
                        title="Snapshot Published",
                        description="Snapshot fixture.",
                        status="published",
                        category="operations",
                        sector="technology",
                        industry="software",
                        business_function="operations",
                        tags=["snapshot"],
                        tags_text="snapshot",
                        price=Decimal("99.00"),
                        currency="USD",
                        license_types=["single_user"],
                        created_at=target_day + timedelta(hours=3),
                        updated_at=target_day + timedelta(hours=3),
                        published_at=target_day + timedelta(hours=4),
                    )
                    late_framework = Framework(
                        contributor_id=contributor.id,
                        title="Late Published",
                        description="Excluded from prior-day snapshot.",
                        status="published",
                        category="operations",
                        sector="technology",
                        industry="software",
                        business_function="operations",
                        tags=["late"],
                        tags_text="late",
                        price=Decimal("120.00"),
                        currency="USD",
                        license_types=["single_user"],
                        created_at=next_day + timedelta(minutes=1),
                        updated_at=next_day + timedelta(minutes=1),
                        published_at=next_day + timedelta(minutes=1),
                    )
                    session.add_all([framework, late_framework])
                    await session.flush()

                    attestation = Attestation(
                        target_type="framework",
                        target_id=framework.id,
                        requestor_id=operator.id,
                        attestor_id=attestor.id,
                        status="report_submitted",
                        outcome="approved",
                        requested_specializations=["ops"],
                        requested_jurisdictions=["us"],
                        fee_amount=Decimal("50.00"),
                        currency="USD",
                        issued_at=target_day + timedelta(hours=6),
                        created_at=target_day + timedelta(hours=6),
                        updated_at=target_day + timedelta(hours=6),
                    )
                    late_attestation = Attestation(
                        target_type="framework",
                        target_id=late_framework.id,
                        requestor_id=late_user.id,
                        attestor_id=attestor.id,
                        status="report_submitted",
                        outcome="approved",
                        requested_specializations=["ops"],
                        requested_jurisdictions=["us"],
                        fee_amount=Decimal("50.00"),
                        currency="USD",
                        issued_at=next_day + timedelta(minutes=2),
                        created_at=next_day + timedelta(minutes=2),
                        updated_at=next_day + timedelta(minutes=2),
                    )
                    session.add_all([attestation, late_attestation])

                    project = Project(
                        operator_id=operator.id,
                        title="Snapshot Project",
                        description="Snapshot dispute fixture.",
                        category="operations",
                        required_deliverables=[{"name": "Playbook"}],
                        budget_min=Decimal("500.00"),
                        budget_max=Decimal("500.00"),
                        currency="USD",
                        status="disputed",
                        milestone_plan_status="draft",
                        expires_at=next_day + timedelta(days=7),
                        created_at=target_day + timedelta(hours=7),
                        updated_at=target_day + timedelta(hours=7),
                    )
                    session.add(project)
                    await session.flush()
                    milestone = Milestone(
                        project_id=project.id,
                        sequence=1,
                        name="Snapshot Milestone",
                        description="Snapshot dispute milestone.",
                        budget=Decimal("500.00"),
                        currency="USD",
                        status="disputed",
                        created_at=target_day + timedelta(hours=7),
                    )
                    session.add(milestone)
                    await session.flush()
                    session.add(
                        Dispute(
                            project_id=project.id,
                            milestone_id=milestone.id,
                            raised_by=operator.id,
                            reason="Snapshot open dispute.",
                            status="open",
                            created_at=target_day + timedelta(hours=8),
                        )
                    )

                    session.add_all(
                        [
                            AuditLog(
                                actor_id=operator.id,
                                action="operator_seen_snapshot",
                                target_type="session",
                                target_id=None,
                                metadata_={},
                                created_at=target_day + timedelta(hours=9),
                            ),
                            AuditLog(
                                actor_id=contributor.id,
                                action="contributor_seen_snapshot",
                                target_type="session",
                                target_id=None,
                                metadata_={},
                                created_at=target_day + timedelta(hours=10),
                            ),
                            AuditLog(
                                actor_id=late_user.id,
                                action="late_seen_snapshot",
                                target_type="session",
                                target_id=None,
                                metadata_={},
                                created_at=next_day + timedelta(minutes=3),
                            ),
                        ]
                    )

                    await _create_transaction(
                        session,
                        payer_id=operator.id,
                        payee_id=contributor.id,
                        amount=Decimal("100.00"),
                        transaction_type="purchase",
                        status="completed",
                        ref_type="framework",
                        created_at=target_day + timedelta(hours=1),
                    )
                    await _create_transaction(
                        session,
                        payer_id=operator.id,
                        payee_id=contributor.id,
                        amount=Decimal("70.00"),
                        transaction_type="purchase",
                        status="completed",
                        ref_type="collection",
                        created_at=target_day + timedelta(hours=2),
                    )
                    await _create_transaction(
                        session,
                        payer_id=operator.id,
                        payee_id=contributor.id,
                        amount=Decimal("500.00"),
                        transaction_type="milestone",
                        status="refunded",
                        ref_type="project_milestone",
                        created_at=target_day + timedelta(hours=3),
                    )
                    await _create_transaction(
                        session,
                        payer_id=operator.id,
                        payee_id=contributor.id,
                        amount=Decimal("300.00"),
                        transaction_type="milestone",
                        status="completed",
                        ref_type="project_milestone",
                        created_at=target_day + timedelta(hours=4),
                    )
                    await _create_transaction(
                        session,
                        payer_id=operator.id,
                        payee_id=contributor.id,
                        amount=Decimal("200.00"),
                        transaction_type="refund",
                        status="refunded",
                        ref_type="project_milestone",
                        created_at=target_day + timedelta(hours=4, minutes=1),
                    )
                    await _create_transaction(
                        session,
                        payer_id=operator.id,
                        payee_id=attestor.id,
                        amount=Decimal("50.00"),
                        transaction_type="attestation_fee",
                        status="completed",
                        ref_type="attestation",
                        created_at=target_day + timedelta(hours=5),
                    )
                    await _create_transaction(
                        session,
                        payer_id=late_user.id,
                        payee_id=contributor.id,
                        amount=Decimal("999.00"),
                        transaction_type="purchase",
                        status="completed",
                        ref_type="framework",
                        created_at=next_day + timedelta(minutes=4),
                    )

            first_result = await admin_beat._snapshot_daily_analytics_impl()
            second_result = await admin_beat._snapshot_daily_analytics_impl()

            response = await client.get(
                "/v1/admin/analytics/dashboard",
                headers=auth_headers(admin.id),
            )

            async with async_session_factory() as session:
                snapshot_rows = (
                    (
                        await session.execute(select(AnalyticsDailySnapshot))
                    )
                    .scalars()
                    .all()
                )
    finally:
        await _cleanup_admin_dashboard_state()
        await engine.dispose()

    assert first_result["snapshot_date"] == "2026-06-11"
    assert first_result["created"] is True
    assert second_result["snapshot_date"] == "2026-06-11"
    assert second_result["created"] is False
    assert len(snapshot_rows) == 2
    latest = next(
        row
        for row in snapshot_rows
        if row.snapshot_date.isoformat() == "2026-06-11"
    )
    assert latest.gmv_total == Decimal("520.00")
    assert latest.gmv_by_source == {
        "framework_purchase": "100.00",
        "collection_purchase": "70.00",
        "project_milestone": "300.00",
        "attestation_fee": "50.00",
    }
    assert latest.active_users == 2
    assert latest.new_registrations == 2
    assert latest.frameworks_published == 1
    assert latest.attestations_issued == 1
    assert latest.disputes_open == 1

    assert response.status_code == 200
    body = response.json()
    assert [row["snapshot_date"] for row in body["trend"]] == [
        "2026-06-10",
        "2026-06-11",
    ]
    assert body["trend"][1] == {
        "snapshot_date": "2026-06-11",
        "gmv_total": "520.00",
        "active_users": 2,
        "new_registrations": 2,
        "frameworks_published": 1,
        "attestations_issued": 1,
        "disputes_open": 1,
    }


async def test_admin_analytics_export_streams_flat_csv_and_audits(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """CSV export must stream flat rows for snapshots and current totals."""
    del migrated_database
    now = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)
    await engine.dispose()
    await _cleanup_admin_dashboard_state()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                admin = await _create_user(
                    session,
                    email=f"admin-export-{uuid4()}@auracles.space",
                    roles=["admin"],
                    created_at=now - timedelta(days=60),
                )
                operator = await _create_user(
                    session,
                    email=f"operator-export-{uuid4()}@auracles.space",
                    roles=["operator"],
                    created_at=now - timedelta(days=5),
                )
                contributor = await _create_user(
                    session,
                    email=f"contributor-export-{uuid4()}@auracles.space",
                    roles=["contributor"],
                    created_at=now - timedelta(days=5),
                )

                session.add_all(
                    [
                        AnalyticsDailySnapshot(
                            snapshot_date=datetime(2026, 6, 10, tzinfo=UTC).date(),
                            gmv_total=Decimal("180.00"),
                            gmv_by_source={
                                "framework_purchase": "100.00",
                                "collection_purchase": "0.00",
                                "project_milestone": "80.00",
                                "attestation_fee": "0.00",
                            },
                            active_users=2,
                            new_registrations=1,
                            frameworks_published=1,
                            attestations_issued=0,
                            disputes_open=1,
                            computed_at=datetime(2026, 6, 11, 0, 5, tzinfo=UTC),
                        ),
                        AnalyticsDailySnapshot(
                            snapshot_date=datetime(2026, 6, 11, tzinfo=UTC).date(),
                            gmv_total=Decimal("220.00"),
                            gmv_by_source={
                                "framework_purchase": "120.00",
                                "collection_purchase": "0.00",
                                "project_milestone": "50.00",
                                "attestation_fee": "50.00",
                            },
                            active_users=3,
                            new_registrations=2,
                            frameworks_published=2,
                            attestations_issued=1,
                            disputes_open=0,
                            computed_at=datetime(2026, 6, 12, 0, 5, tzinfo=UTC),
                        ),
                    ]
                )
                await session.flush()

                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("100.00"),
                    transaction_type="purchase",
                    status="completed",
                    ref_type="framework",
                    created_at=now - timedelta(hours=2),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("90.00"),
                    transaction_type="purchase",
                    status="completed",
                    ref_type="collection",
                    created_at=now - timedelta(days=2),
                )
                await _create_transaction(
                    session,
                    payer_id=operator.id,
                    payee_id=contributor.id,
                    amount=Decimal("70.00"),
                    transaction_type="milestone",
                    status="completed",
                    ref_type="project_milestone",
                    created_at=now - timedelta(days=10),
                )

            response = await client.get(
                "/v1/admin/analytics/export?from=2026-06-10&to=2026-06-11",
                headers=auth_headers(admin.id),
            )

            async with async_session_factory() as audit_session:
                audit_rows = (
                    (
                        await audit_session.execute(
                            select(AuditLog).where(
                                AuditLog.action == "analytics_exported"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
    finally:
        await _cleanup_admin_dashboard_state()
        await engine.dispose()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="admin-analytics-2026-06-10-to-2026-06-11.csv"'
    )

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [row["row_type"] for row in rows] == [
        "snapshot",
        "snapshot",
        "current_window",
        "current_window",
        "current_window",
        "current_state",
    ]
    assert rows[0] == {
        "row_type": "snapshot",
        "snapshot_date": "2026-06-10",
        "window": "",
        "gmv_total": "180.00",
        "gmv_framework_purchase": "100.00",
        "gmv_collection_purchase": "0.00",
        "gmv_project_milestone": "80.00",
        "gmv_attestation_fee": "0.00",
        "active_users": "2",
        "new_registrations": "1",
        "frameworks_published": "1",
        "frameworks_published_total": "",
        "attestations_issued": "0",
        "disputes_open_total": "1",
        "disputes_open_projects": "",
        "disputes_open_attestations": "",
        "computed_at": "2026-06-11T00:05:00+00:00",
    }
    assert rows[2]["row_type"] == "current_window"
    assert rows[2]["window"] == "today"
    assert rows[2]["gmv_total"] == "100.00"
    assert rows[2]["gmv_framework_purchase"] == "100.00"
    assert rows[2]["gmv_collection_purchase"] == "0.00"
    assert rows[2]["gmv_project_milestone"] == "0.00"
    assert rows[2]["gmv_attestation_fee"] == "0.00"
    assert rows[3]["window"] == "last_7_days"
    assert rows[3]["gmv_total"] == "190.00"
    assert rows[4]["window"] == "last_30_days"
    assert rows[4]["gmv_total"] == "260.00"
    assert rows[5] == {
        "row_type": "current_state",
        "snapshot_date": "",
        "window": "",
        "gmv_total": "",
        "gmv_framework_purchase": "",
        "gmv_collection_purchase": "",
        "gmv_project_milestone": "",
        "gmv_attestation_fee": "",
        "active_users": "",
        "new_registrations": "",
        "frameworks_published": "",
        "frameworks_published_total": "0",
        "attestations_issued": "",
        "disputes_open_total": "0",
        "disputes_open_projects": "0",
        "disputes_open_attestations": "0",
        "computed_at": "",
    }

    assert len(audit_rows) == 1
    assert audit_rows[0].actor_id == admin.id
    assert audit_rows[0].target_type == "analytics_export"
    assert audit_rows[0].metadata_ == {
        "from": "2026-06-10",
        "to": "2026-06-11",
        "row_count": 6,
    }


async def test_admin_analytics_export_rejects_ranges_longer_than_366_days(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """CSV export must reject unbounded date spans."""
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup_admin_dashboard_state()
    try:
        async with async_session_factory() as session:
            async with session.begin():
                admin = await _create_user(
                    session,
                    email=f"admin-export-range-{uuid4()}@auracles.space",
                    roles=["admin"],
                    created_at=now - timedelta(days=10),
                )

            response = await client.get(
                "/v1/admin/analytics/export?from=2025-01-01&to=2026-01-03",
                headers=auth_headers(admin.id),
            )
    finally:
        await _cleanup_admin_dashboard_state()
        await engine.dispose()

    assert response.status_code == 422
    assert response.json()["detail"] == "Date range cannot exceed 366 days."
