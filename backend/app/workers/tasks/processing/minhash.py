"""MinHash and SimHash fingerprint step for Artifact processing."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

import numpy as np
from datasketch import MinHash  # type: ignore[import-untyped]
from loguru import logger

from app.core.database import async_session_factory
from app.modules.frameworks.models_artifact import Artifact
from app.workers.async_runner import run_async
from app.workers.celery_app import app

MINHASH_PERMUTATIONS = 128
SHINGLE_SIZE = 5
TOKEN_PATTERN = re.compile(r"\b[\w'-]+\b")


def tokenize(text: str) -> list[str]:
    """Normalize text into lowercase tokens for similarity fingerprints."""
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def make_shingles(tokens: list[str]) -> list[str]:
    """Return 5-word shingles, or one low-confidence shingle for tiny text."""
    if not tokens:
        return []
    if len(tokens) < SHINGLE_SIZE:
        return [" ".join(tokens)]
    return [
        " ".join(tokens[index : index + SHINGLE_SIZE])
        for index in range(len(tokens) - SHINGLE_SIZE + 1)
    ]


def minhash_signature_from_text(text: str) -> tuple[bytes, int]:
    """Compute a 128-permutation MinHash signature and shingle count."""
    minhash = MinHash(num_perm=MINHASH_PERMUTATIONS)
    shingles = make_shingles(tokenize(text))
    for shingle in shingles:
        minhash.update(shingle.encode("utf-8"))
    signature = np.asarray(minhash.hashvalues, dtype=">u8").tobytes()
    return signature, len(shingles)


def minhash_from_signature(signature: bytes) -> MinHash:
    """Rehydrate a MinHash object from persisted BYTEA signature bytes."""
    minhash = MinHash(num_perm=MINHASH_PERMUTATIONS)
    minhash.hashvalues = np.frombuffer(signature, dtype=">u8").astype(np.uint64)
    return minhash


def simhash_from_text(text: str) -> int:
    """Compute a signed 64-bit SimHash pre-filter from token frequencies."""
    weights = [0] * 64
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big", signed=False)
        for bit_index in range(64):
            if value & (1 << bit_index):
                weights[bit_index] += 1
            else:
                weights[bit_index] -= 1
    unsigned = 0
    for bit_index, weight in enumerate(weights):
        if weight >= 0:
            unsigned |= 1 << bit_index
    if unsigned >= 2**63:
        return unsigned - 2**64
    return unsigned


async def _compute_minhash_impl(artifact_id: str) -> dict[str, Any]:
    """Persist MinHash, SimHash, and shingle metadata for an Artifact."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        metadata = dict(artifact.metadata_vector or {})
        extraction = metadata.get("extraction", {})
        text = str(extraction.get("text", ""))
        signature, shingle_count = minhash_signature_from_text(text)
        metadata["minhash"] = {
            "num_perm": MINHASH_PERMUTATIONS,
            "shingle_size": SHINGLE_SIZE,
            "shingle_count": shingle_count,
            "low_confidence": shingle_count <= 1,
        }
        artifact.metadata_vector = metadata
        artifact.minhash_signature = signature
        artifact.simhash = simhash_from_text(text)
        await db.commit()
    return {"artifact_id": artifact_id, "status": "minhash_computed"}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def compute_minhash(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for Artifact MinHash fingerprinting."""
    log = logger.bind(
        module="artifacts",
        action="compute_minhash",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_compute_minhash_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
