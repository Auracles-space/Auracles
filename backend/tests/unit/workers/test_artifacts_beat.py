"""Unit tests for the artifact stale-lease reaper and orphan sweep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.database import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact

pytestmark = pytest.mark.asyncio


async def _truncate() -> None:
    async with async_session_factory() as s:
        await s.execute(
            text(
                "TRUNCATE TABLE "
                f"{Artifact.__tablename__}, {Framework.__tablename__}, "
                f"{User.__tablename__} RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()


async def _seed_framework(session) -> Framework:
    contributor = User(email=f"{uuid4()}@a.space", display_name="R",
                       email_verified=True, password_hash=None)
    framework = Framework(
        contributor_id=uuid4(), title="Reaper FW", description="reaper test fw",
        category="framework", sector="financial_services", industry="fund_management",
        business_function="risk_management", tags=["r"], tags_text="r",
        jurisdiction="us", complexity=3, org_size="mid_market",
        lifecycle_stage="scale", price=Decimal("1.00"), currency="USD",
        license_types=["single_user"], commercial_rights="x",
        usage_restrictions="x", status="draft",
    )
    session.add(contributor)
    await session.flush()
    framework.contributor_id = contributor.id
    session.add(framework)
    await session.flush()
    return framework


async def test_reaper_fails_stale_processing_rows(monkeypatch):
    """A row processing past the lease TTL is flipped to failed."""
    await engine.dispose()
    await _truncate()
    from app.workers.tasks import artifacts_beat

    monkeypatch.setattr(
        artifacts_beat, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket",
                                artifact_processing_lease_minutes=30,
                                artifact_orphan_sweep_minutes=60),
    )
    # No S3 orphans in this test.
    monkeypatch.setattr(artifacts_beat.s3.storage, "list_keys",
                        lambda bucket, prefix: [], raising=False)

    async with async_session_factory() as session:
        async with session.begin():
            framework = await _seed_framework(session)
            stale = Artifact(
                framework_id=framework.id, name="s.pdf",
                file_key="frameworks/x/artifacts/s.pdf", file_size=1,
                mime_type="application/pdf", processing_status="processing",
                processing_started_at=datetime.now(UTC) - timedelta(minutes=31),
            )
            fresh = Artifact(
                framework_id=framework.id, name="f.pdf",
                file_key="frameworks/x/artifacts/f.pdf", file_size=1,
                mime_type="application/pdf", processing_status="processing",
                processing_started_at=datetime.now(UTC),
            )
            session.add_all([stale, fresh])
            await session.flush()
            stale_id, fresh_id = stale.id, fresh.id

    result = await artifacts_beat._reap_stalled_artifacts_impl()

    async with async_session_factory() as session:
        assert (await session.get(Artifact, stale_id)).processing_status == "failed"
        assert (await session.get(Artifact, fresh_id)).processing_status == "processing"
    assert result["reaped"] == 1
    await _truncate()
    await engine.dispose()


async def test_orphan_sweep_deletes_unreferenced_keys(monkeypatch):
    """Only the orphaned, aged key is deleted; live and source-preview keys survive."""
    await engine.dispose()
    await _truncate()
    from app.workers.tasks import artifacts_beat

    monkeypatch.setattr(
        artifacts_beat, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket",
                                artifact_processing_lease_minutes=30,
                                artifact_orphan_sweep_minutes=60),
    )
    old_timestamp = datetime.now(UTC) - timedelta(minutes=120)
    monkeypatch.setattr(
        artifacts_beat.s3.storage, "list_keys",
        lambda bucket, prefix: [
            (old_timestamp, "frameworks/x/artifacts/live.pdf"),
            (old_timestamp, "frameworks/x/artifacts/orphan.pdf"),
            (old_timestamp, "frameworks/x/artifacts/y/source-preview/z.png"),
        ],
        raising=False,
    )
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        artifacts_beat.s3.storage, "delete_object",
        lambda bucket, key: deleted.append((bucket, key)),
        raising=False,
    )

    async with async_session_factory() as session:
        async with session.begin():
            framework = await _seed_framework(session)
            live = Artifact(
                framework_id=framework.id, name="live.pdf",
                file_key="frameworks/x/artifacts/live.pdf", file_size=1,
                mime_type="application/pdf", processing_status="processed",
            )
            session.add(live)

    result = await artifacts_beat._reap_stalled_artifacts_impl()

    assert deleted == [("bucket", "frameworks/x/artifacts/orphan.pdf")]
    assert result["swept"] == 1
    await _truncate()
    await engine.dispose()


async def test_orphan_sweep_spares_recent_objects(monkeypatch):
    """An orphan key younger than the sweep TTL is never deleted.

    Proves the in-flight-upload protection: Task 5's upload-then-commit
    ordering means a live upload's bytes can exist in S3 before its Artifact
    row commits, so a recent key must survive the sweep even if it currently
    has no matching row.
    """
    await engine.dispose()
    await _truncate()
    from app.workers.tasks import artifacts_beat

    monkeypatch.setattr(
        artifacts_beat, "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket",
                                artifact_processing_lease_minutes=30,
                                artifact_orphan_sweep_minutes=60),
    )
    recent_timestamp = datetime.now(UTC)
    monkeypatch.setattr(
        artifacts_beat.s3.storage, "list_keys",
        lambda bucket, prefix: [
            (recent_timestamp, "frameworks/x/artifacts/orphan.pdf"),
        ],
        raising=False,
    )
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        artifacts_beat.s3.storage, "delete_object",
        lambda bucket, key: deleted.append((bucket, key)),
        raising=False,
    )

    result = await artifacts_beat._reap_stalled_artifacts_impl()

    assert deleted == []
    assert result["swept"] == 0
    await _truncate()
    await engine.dispose()
