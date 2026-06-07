"""Artifact processing pipeline orchestration.

Runs implemented processing steps after virus scanning. Later slices extend this
with external rarity, thumbnails, and search indexing.
"""

from __future__ import annotations

from typing import Any

from app.workers.tasks.processing.extract import _extract_text_impl
from app.workers.tasks.processing.metadata import _compute_metadata_impl
from app.workers.tasks.processing.minhash import _compute_minhash_impl
from app.workers.tasks.processing.pii import _detect_pii_impl
from app.workers.tasks.processing.rarity_external import _compute_external_rarity_impl
from app.workers.tasks.processing.rarity_internal import _compute_internal_rarity_impl


async def _process_artifact_impl(artifact_id: str) -> dict[str, Any]:
    """Run the currently implemented Artifact pipeline steps in order."""
    extraction = await _extract_text_impl(artifact_id)
    if extraction["status"] in {"missing", "failed"}:
        return {
            "artifact_id": artifact_id,
            "status": extraction["status"],
            "steps": {"extract": extraction},
        }

    pii = await _detect_pii_impl(artifact_id)
    result = {
        "artifact_id": artifact_id,
        "status": pii["status"],
        "steps": {"extract": extraction, "pii": pii},
    }
    if pii["status"] != "clear":
        return result

    metadata = await _compute_metadata_impl(artifact_id)
    minhash = await _compute_minhash_impl(artifact_id)
    rarity_internal = await _compute_internal_rarity_impl(artifact_id)
    rarity_external = await _compute_external_rarity_impl(artifact_id)
    return {
        "artifact_id": artifact_id,
        "status": rarity_external["status"],
        "steps": {
            "extract": extraction,
            "pii": pii,
            "metadata": metadata,
            "minhash": minhash,
            "rarity_internal": rarity_internal,
            "rarity_external": rarity_external,
        },
    }
