"""Redis-backed MinHash LSH index helpers.

The database remains the source of truth for published Artifacts. These Redis
keys are an acceleration structure for future rarity lookups and are safe to
rebuild from published database rows if cache state is lost.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.redis import get_redis
from app.modules.frameworks.models_artifact import Artifact

MINHASH_PERMUTATIONS = 128
LSH_BANDS = 32
LSH_ROWS_PER_BAND = MINHASH_PERMUTATIONS // LSH_BANDS
MINHASH_WORD_BYTES = 8
ARTIFACT_LSH_PREFIX = "artifact_lsh:v1"


def _redis_text(value: object) -> str:
    """Normalize Redis bytes/strings to text."""
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _band_keys(signature: bytes) -> list[str]:
    """Return deterministic LSH band keys for one MinHash signature."""
    expected_length = MINHASH_PERMUTATIONS * MINHASH_WORD_BYTES
    if len(signature) != expected_length:
        return []

    keys: list[str] = []
    band_size = LSH_ROWS_PER_BAND * MINHASH_WORD_BYTES
    for band_index in range(LSH_BANDS):
        start = band_index * band_size
        band_digest = hashlib.sha256(signature[start : start + band_size]).hexdigest()
        keys.append(f"{ARTIFACT_LSH_PREFIX}:band:{band_index}:{band_digest}")
    return keys


def _artifact_key(artifact_id: UUID) -> str:
    """Return the Redis key tracking band membership for one Artifact."""
    return f"{ARTIFACT_LSH_PREFIX}:artifact:{artifact_id}"


async def index_artifact_signature(artifact_id: UUID, signature: bytes) -> None:
    """Insert one Artifact signature into Redis LSH bands idempotently."""
    band_keys = _band_keys(signature)
    if not band_keys:
        return

    redis = get_redis()
    artifact_key = _artifact_key(artifact_id)
    existing_keys = await cast(Awaitable[set[Any]], redis.smembers(artifact_key))
    for raw_key in existing_keys:
        await cast(
            Awaitable[int],
            redis.srem(_redis_text(raw_key), str(artifact_id)),
        )
    await redis.delete(artifact_key)
    for band_key in band_keys:
        await cast(Awaitable[int], redis.sadd(band_key, str(artifact_id)))
        await cast(Awaitable[int], redis.sadd(artifact_key, band_key))


async def remove_artifact_signature(artifact_id: UUID) -> None:
    """Remove one Artifact from all Redis LSH bands idempotently."""
    redis = get_redis()
    artifact_key = _artifact_key(artifact_id)
    band_keys = await cast(Awaitable[set[Any]], redis.smembers(artifact_key))
    for raw_key in band_keys:
        await cast(
            Awaitable[int],
            redis.srem(_redis_text(raw_key), str(artifact_id)),
        )
    await redis.delete(artifact_key)


async def index_framework_artifacts(framework_id: UUID) -> None:
    """Index all current Framework Artifact signatures for published lookup."""
    async with async_session_factory() as db:
        rows = await db.execute(
            select(Artifact.id, Artifact.minhash_signature).where(
                Artifact.framework_id == framework_id,
                Artifact.current_for_framework.is_(True),
                Artifact.minhash_signature.is_not(None),
            )
        )
        signatures: list[tuple[UUID, bytes]] = [
            (artifact_id, signature)
            for artifact_id, signature in rows.all()
            if signature is not None
        ]

    for artifact_id, signature in signatures:
        await index_artifact_signature(artifact_id, signature)


async def remove_framework_artifacts_from_index(framework_id: UUID) -> None:
    """Remove all current Framework Artifacts from Redis LSH bands."""
    async with async_session_factory() as db:
        artifact_ids = (
            (
                await db.execute(
                    select(Artifact.id).where(
                        Artifact.framework_id == framework_id,
                        Artifact.current_for_framework.is_(True),
                        Artifact.minhash_signature.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    for artifact_id in artifact_ids:
        await remove_artifact_signature(artifact_id)
