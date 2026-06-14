"""Redis-backed MinHash LSH index helper tests.

Covers the band-key derivation and the Redis index/remove lifecycle in
``app/workers/tasks/processing/minhash_index.py``. The index is an
acceleration structure; the database stays the source of truth. Tests run
against the real cache client returned by ``get_redis`` and clean up the keys
they create, using a unique Artifact id per test to avoid collisions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.workers.tasks.processing import minhash_index

_SIGNATURE_BYTES = minhash_index.MINHASH_PERMUTATIONS * minhash_index.MINHASH_WORD_BYTES


def _signature() -> bytes:
    """Return a well-formed, non-trivial MinHash signature."""
    return bytes(index % 256 for index in range(_SIGNATURE_BYTES))


def test_band_keys_returns_one_key_per_band_for_valid_signature() -> None:
    """A correctly sized signature yields exactly one prefixed key per band."""
    keys = minhash_index._band_keys(_signature())

    assert len(keys) == minhash_index.LSH_BANDS
    assert all(
        key.startswith(f"{minhash_index.ARTIFACT_LSH_PREFIX}:band:") for key in keys
    )


def test_band_keys_rejects_wrong_length_signature() -> None:
    """A signature of the wrong byte length yields no band keys."""
    assert minhash_index._band_keys(b"too-short") == []


async def test_index_then_remove_artifact_signature_roundtrip() -> None:
    """Indexing registers band membership; re-indexing is idempotent; remove clears."""
    artifact_id = uuid4()
    signature = _signature()
    redis = get_redis()
    artifact_key = minhash_index._artifact_key(artifact_id)
    band_keys = minhash_index._band_keys(signature)

    try:
        await minhash_index.index_artifact_signature(artifact_id, signature)
        # Re-index to exercise the existing-membership cleanup branch.
        await minhash_index.index_artifact_signature(artifact_id, signature)

        member_count = await redis.scard(artifact_key)
        first_band_members = await redis.smembers(band_keys[0])

        assert int(member_count) == minhash_index.LSH_BANDS
        assert str(artifact_id).encode() in {
            member if isinstance(member, bytes) else member.encode()
            for member in first_band_members
        }

        await minhash_index.remove_artifact_signature(artifact_id)
        assert await redis.exists(artifact_key) == 0
        assert await redis.scard(band_keys[0]) == 0
    finally:
        await redis.delete(artifact_key, *band_keys)
        await redis.aclose()


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure framework/artifact tables exist for the indexing test."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def framework_artifact_state() -> AsyncIterator[None]:
    """Reset framework/artifact rows around the indexing test."""
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def test_index_framework_artifacts_indexes_current_signed_artifacts(
    migrated_database: None,
    framework_artifact_state: None,
) -> None:
    """Only current Artifacts with a stored signature get indexed for a Framework."""
    del migrated_database, framework_artifact_state
    signature = _signature()
    async with async_session_factory() as session:
        async with session.begin():
            contributor = User(
                email=f"minhash-{uuid4()}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="MinHash Contributor",
                email_verified=True,
                kyc_status="verified",
            )
            session.add(contributor)
            await session.flush()
            framework = Framework(
                id=uuid4(),
                contributor_id=contributor.id,
                title="MinHash Framework",
                description="Index smoke framework.",
                version="1.0.0",
                status="published",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk"],
                tags_text="risk",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            artifact = Artifact(
                id=uuid4(),
                framework_id=framework.id,
                name="signed.pdf",
                file_key=f"frameworks/{framework.id}/artifacts/signed.pdf",
                file_size=2048,
                mime_type="application/pdf",
                current_for_framework=True,
                minhash_signature=signature,
            )
            session.add(artifact)
            artifact_id = artifact.id
            framework_id = framework.id

    redis = get_redis()
    artifact_key = minhash_index._artifact_key(artifact_id)
    band_keys = minhash_index._band_keys(signature)
    try:
        await minhash_index.index_framework_artifacts(framework_id)
        assert int(await redis.scard(artifact_key)) == minhash_index.LSH_BANDS
    finally:
        await redis.delete(artifact_key, *band_keys)
        await redis.aclose()
