"""Unit tests for annual attestor earnings summaries (Module 6d)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from freezegun import freeze_time
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, Transaction
from app.modules.invoicing.models import Invoice, InvoiceCounter
from app.modules.notifications.models import (
    Notification,
    NotificationDeliveryMarker,
)
from app.workers.tasks import invoicing_beat, project_notifications


class FakeSummaryStorage:
    """S3 storage double that records annual-summary uploads."""

    def __init__(self) -> None:
        """Create empty upload history."""
        self.uploads: list[tuple[str, str, bytes, str]] = []

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        body: bytes,
        mime_type: str,
    ) -> None:
        """Record one uploaded summary document."""
        self.uploads.append((bucket, key, body, mime_type))


class FakeNotificationEmailTask:
    """Email-task double that records summary-ready email fanout."""

    def __init__(self) -> None:
        """Create empty email fanout history."""
        self.calls: list[dict[str, str | None]] = []

    def delay(
        self,
        *,
        email: str,
        title: str,
        body: str,
        link: str | None,
    ) -> None:
        """Record one email-notification enqueue."""
        self.calls.append(
            {
                "email": email,
                "title": title,
                "body": body,
                "link": link,
            }
        )


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is upgraded to alembic head."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
def annual_summary_context(
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, object]]:
    """Reset annual-summary rows and install storage/notification doubles."""
    del migrated_database
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(sync_engine)
    fake_storage = FakeSummaryStorage()
    fake_email_task = FakeNotificationEmailTask()

    def cleanup() -> None:
        """Delete seeded annual-summary rows in foreign-key-safe order."""
        with session_factory() as session:
            session.execute(delete(NotificationDeliveryMarker))
            session.execute(delete(Notification))
            session.execute(delete(Invoice))
            session.execute(delete(InvoiceCounter))
            session.execute(delete(Attestation))
            session.execute(delete(Escrow))
            session.execute(delete(Transaction))
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()

    monkeypatch.setattr(invoicing_beat.s3, "storage", fake_storage)
    monkeypatch.setattr(
        invoicing_beat,
        "render_annual_summary_pdf",
        lambda **kwargs: b"%PDF-ANNUAL-SUMMARY%",
    )
    monkeypatch.setattr(
        invoicing_beat.generate_annual_earnings_summary,
        "delay",
        lambda attestor_id, year: invoicing_beat.generate_annual_earnings_summary.apply(
            args=[attestor_id, year]
        ).get(),
    )
    monkeypatch.setattr(
        invoicing_beat.dispatch_project_notification,
        "delay",
        lambda **kwargs: project_notifications.dispatch_project_notification.apply(
            kwargs=kwargs
        ).get(),
    )
    monkeypatch.setattr(
        project_notifications,
        "send_project_notification_email",
        fake_email_task,
    )

    async def _publish_to_channel(
        _channel: str,
        _event: str,
        _payload: dict[str, object],
    ) -> None:
        """Suppress realtime fanout during unit tests."""

    monkeypatch.setattr(
        project_notifications,
        "publish_to_channel",
        _publish_to_channel,
    )

    cleanup()
    try:
        yield {
            "session_factory": session_factory,
            "storage": fake_storage,
            "email_task": fake_email_task,
        }
    finally:
        cleanup()
        sync_engine.dispose()


def _create_user(
    session_factory: sessionmaker,
    *,
    email: str,
    roles: list[str],
) -> UUID:
    """Create one verified user with approved role rows."""
    with session_factory() as session:
        user = User(
            email=email,
            password_hash=hash_password("CorrectHorse9"),
            display_name=email.split("@")[0],
            email_verified=True,
        )
        session.add(user)
        session.flush()
        for role in roles:
            session.add(
                UserRole(
                    user_id=user.id,
                    role=role,
                    approved_at=datetime.now(UTC),
                )
            )
        session.commit()
        return user.id


def _seed_closed_attestation_fee(
    session_factory: sessionmaker,
    *,
    attestor_id: UUID,
    requestor_id: UUID,
    closed_at: datetime,
) -> None:
    """Seed one closed attestation with a released fee escrow."""
    with session_factory() as session:
        attestation = Attestation(
            target_type="framework",
            target_id=uuid4(),
            requestor_id=requestor_id,
            attestor_id=attestor_id,
            status="closed",
            outcome="approved",
            review_type="expert",
            requested_specializations=[],
            requested_jurisdictions=[],
            fee_amount=Decimal("500.00"),
            currency="USD",
            report_published_eligible=True,
            closed_at=closed_at,
        )
        session.add(attestation)
        session.flush()
        transaction = Transaction(
            payer_id=requestor_id,
            payee_id=None,
            amount=Decimal("500.00"),
            currency="USD",
            platform_commission=Decimal("0.00"),
            net_amount=Decimal("500.00"),
            transaction_type="attestation_fee",
            status="completed",
            provider="stripe",
            provider_ref=f"pi_annual_{uuid4().hex[:8]}",
            ref_id=attestation.id,
            ref_type="attestation",
            updated_at=closed_at,
        )
        session.add(transaction)
        session.flush()
        escrow = Escrow(
            ref_id=attestation.id,
            ref_type="attestation",
            amount=Decimal("500.00"),
            currency="USD",
            status="released",
            release_conditions={},
            transaction_id=transaction.id,
            released_at=closed_at,
        )
        session.add(escrow)
        session.flush()
        attestation.escrow_id = escrow.id
        session.commit()


@freeze_time("2027-01-02")
def test_generates_summary_per_earner_not_for_zero(
    annual_summary_context: dict[str, object],
) -> None:
    """Beat run renders one PDF per prior-year earner and skips zero earners."""
    session_factory = annual_summary_context["session_factory"]
    assert isinstance(session_factory, sessionmaker)
    attestor_a = _create_user(
        session_factory,
        email="annual-attestor-a@auracles.space",
        roles=["attestor"],
    )
    attestor_b = _create_user(
        session_factory,
        email="annual-attestor-b@auracles.space",
        roles=["attestor"],
    )
    zero_earner = _create_user(
        session_factory,
        email="annual-zero@auracles.space",
        roles=["attestor"],
    )
    requestor = _create_user(
        session_factory,
        email="annual-requestor@auracles.space",
        roles=["operator"],
    )
    _seed_closed_attestation_fee(
        session_factory,
        attestor_id=attestor_a,
        requestor_id=requestor,
        closed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    _seed_closed_attestation_fee(
        session_factory,
        attestor_id=attestor_b,
        requestor_id=requestor,
        closed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )

    result = invoicing_beat.generate_annual_earnings_summaries.apply().get()

    storage = annual_summary_context["storage"]
    assert isinstance(storage, FakeSummaryStorage)
    keys = {key for (_bucket, key, _body, _mime) in storage.uploads}
    assert result["year"] == 2026
    assert f"annual-summaries/{attestor_a}/2026.pdf" in keys
    assert f"annual-summaries/{attestor_b}/2026.pdf" in keys
    assert not any(str(zero_earner) in key for key in keys)


@freeze_time("2027-01-02")
def test_summary_generation_is_idempotent_for_key_and_notification(
    annual_summary_context: dict[str, object],
) -> None:
    """Re-running one annual summary overwrites the key and dedupes fanout."""
    session_factory = annual_summary_context["session_factory"]
    assert isinstance(session_factory, sessionmaker)
    attestor = _create_user(
        session_factory,
        email="annual-repeat@auracles.space",
        roles=["attestor"],
    )
    requestor = _create_user(
        session_factory,
        email="annual-repeat-requestor@auracles.space",
        roles=["operator"],
    )
    _seed_closed_attestation_fee(
        session_factory,
        attestor_id=attestor,
        requestor_id=requestor,
        closed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )

    first = invoicing_beat.generate_annual_earnings_summary.apply(
        args=[str(attestor), 2026]
    ).get()
    second = invoicing_beat.generate_annual_earnings_summary.apply(
        args=[str(attestor), 2026]
    ).get()

    assert first["status"] == "generated"
    assert second["status"] == "generated"

    storage = annual_summary_context["storage"]
    assert isinstance(storage, FakeSummaryStorage)
    uploaded_keys = [key for (_bucket, key, _body, _mime) in storage.uploads]
    assert uploaded_keys == [
        f"annual-summaries/{attestor}/2026.pdf",
        f"annual-summaries/{attestor}/2026.pdf",
    ]

    email_task = annual_summary_context["email_task"]
    assert isinstance(email_task, FakeNotificationEmailTask)
    assert len(email_task.calls) == 1
    assert email_task.calls[0]["link"] == "/attestations"

    with session_factory() as session:
        notifications = session.query(Notification).filter(
            Notification.user_id == attestor,
            Notification.dedupe_key
            == f"attestation_annual_summary:{attestor}:2026",
        )
        assert notifications.count() == 1
