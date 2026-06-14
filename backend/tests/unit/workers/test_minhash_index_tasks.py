"""Redis-backed MinHash LSH index helper tests.

Covers band-key derivation and the index/remove lifecycle in
``app/workers/tasks/processing/minhash_index.py``. The index is an
acceleration structure; the database stays the source of truth. A small
in-memory async fake stands in for the cache client so the tests are
deterministic and never bind a shared connection pool to a per-test event
loop.
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
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.workers.tasks.processing import minhash_index

_SIGNATURE_BYTES = minhash_index.MINHASH_PERMUTATIONS * minhash_index.MINHASH_WORD_BYTES


class _FakeRedis:
    """Minimal in-memory async Redis set store for LSH index tests."""

    def __init__(self) -> None:
        """Start with no sets."""
        self.sets: dict[str, set[str]] = {}

    async def sadd(self, key: str, *members: str) -> int:
        """Add members to a set."""
        self.sets.setdefault(key, set()).update(members)
        return len(members)

    async def srem(self, key: str, *members: str) -> int:
        """Remove members from a set if present."""
        bucket = self.sets.get(key)
        if bucket is not None:
            bucket.difference_update(members)
        return 0

    async def smembers(self, key: str) -> set[str]:
        """Return a copy of the set's members."""
        return set(self.sets.get(key, set()))

    async def scard(self, key: str) -> int:
        """Return the set cardinality."""
        return len(self.sets.get(key, set()))

    async def delete(self, *keys: str) -> int:
        """Delete keys, returning how many existed."""
        removed = 0
        for key in keys:
            if key in self.sets:
                del self.sets[key]
                removed += 1
        return removed

    async def exists(self, key: str) -> int:
        """Return 1 if the key exists, else 0."""
        return 1 if key in self.sets else 0


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


async def test_index_then_remove_artifact_signature_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indexing registers band membership; re-indexing is idempotent; remove clears."""
    fake = _FakeRedis()
    monkeypatch.setattr(minhash_index, "get_redis", lambda: fake)
    artifact_id = uuid4()
    signature = _signature()
    artifact_key = minhash_index._artifact_key(artifact_id)
    band_keys = minhash_index._band_keys(signature)

    await minhash_index.index_artifact_signature(artifact_id, signature)
    # Re-index to exercise the existing-membership cleanup branch.
    await minhash_index.index_artifact_signature(artifact_id, signature)

    assert await fake.scard(artifact_key) == minhash_index.LSH_BANDS
    assert str(artifact_id) in await fake.smembers(band_keys[0])

    await minhash_index.remove_artifact_signature(artifact_id)
    assert await fake.exists(artifact_key) == 0
    assert await fake.scard(band_keys[0]) == 0


async def test_index_artifact_signature_ignores_malformed_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrong-length signature indexes nothing rather than raising."""
    fake = _FakeRedis()
    monkeypatch.setattr(minhash_index, "get_redis", lambda: fake)
    artifact_id = uuid4()

    await minhash_index.index_artifact_signature(artifact_id, b"too-short")

    assert fake.sets == {}


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only current Artifacts with a stored signature get indexed for a Framework."""
    del migrated_database, framework_artifact_state
    fake = _FakeRedis()
    monkeypatch.setattr(minhash_index, "get_redis", lambda: fake)
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

    await minhash_index.index_framework_artifacts(framework_id)

    artifact_key = minhash_index._artifact_key(artifact_id)
    assert await fake.scard(artifact_key) == minhash_index.LSH_BANDS
