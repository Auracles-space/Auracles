"""Artifact processing pipeline orchestration.

Slice 4 wires extraction and PII detection after virus scanning. Later slices
extend this orchestrator with metadata, MinHash, rarity, thumbnails, and search.
"""

from __future__ import annotations

from typing import Any

from app.workers.tasks.processing.extract import _extract_text_impl
from app.workers.tasks.processing.pii import _detect_pii_impl


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
    return {
        "artifact_id": artifact_id,
        "status": pii["status"],
        "steps": {"extract": extraction, "pii": pii},
    }
