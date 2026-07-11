"""The scan pipeline backfills content_sha256 for upload-path artifacts."""

from __future__ import annotations

import hashlib
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
    """Clear the tables this test seeds so runs stay isolated."""
    async with async_session_factory() as s:
        await s.execute(
            text(
                "TRUNCATE TABLE "
                f"{Artifact.__tablename__}, {Framework.__tablename__}, "
                f"{User.__tablename__} RESTART IDENTITY CASCADE"
            )
        )
        await s.commit()


async def test_scan_sets_content_hash_when_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean scan of an artifact with NULL hash records sha256 of its bytes."""
    await engine.dispose()
    await _truncate()
    from app.workers.tasks import artifacts as artifacts_task

    known = b"UPLOADED-BYTES"
    async with async_session_factory() as session:
        async with session.begin():
            contributor = User(
                email=f"{uuid4()}@a.space",
                display_name="H",
                email_verified=True,
                password_hash=None,
            )
            session.add(contributor)
            await session.flush()
            framework = Framework(
                contributor_id=contributor.id,
                title="Hash FW",
                description="hash pipeline fw",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["h"],
                tags_text="h",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("1.00"),
                currency="USD",
                license_types=["single_user"],
                commercial_rights="x",
                usage_restrictions="x",
                status="draft",
            )
            session.add(framework)
            await session.flush()
            artifact = Artifact(
                framework_id=framework.id,
                name="u.pdf",
                file_key="frameworks/x/artifacts/u.pdf",
                file_size=len(known),
                mime_type="application/pdf",
                processing_status="pending",
            )
            session.add(artifact)
            await session.flush()
            artifact_id = artifact.id

    def _fake_download(bucket: str, key: str, destination: str) -> None:
        with open(destination, "wb") as handle:
            handle.write(known)

    monkeypatch.setattr(artifacts_task.s3.storage, "download_file", _fake_download)

    await artifacts_task._scan_artifact_impl(
        str(artifact_id),
        scan_file=lambda path: "clean",
        process_task=SimpleNamespace(delay=lambda _id: None),
    )

    async with async_session_factory() as session:
        row = await session.get(Artifact, artifact_id)
        assert row is not None
        assert row.content_sha256 == hashlib.sha256(known).hexdigest()
    await _truncate()
    await engine.dispose()
