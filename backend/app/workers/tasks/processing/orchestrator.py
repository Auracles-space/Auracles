"""Artifact processing pipeline orchestration.

Runs implemented processing steps after virus scanning. Each step persists its
own database state so a failed task can be retried without repeating unrelated
request-path work.
"""

from __future__ import annotations

from typing import Any

from app.modules.frameworks.pipeline_gate import (
    evaluate_framework_pipeline_for_artifact,
)
from app.workers.tasks.processing.blend import _compute_final_rarity_impl
from app.workers.tasks.processing.extract import _extract_text_impl
from app.workers.tasks.processing.metadata import _compute_metadata_impl
from app.workers.tasks.processing.minhash import _compute_minhash_impl
from app.workers.tasks.processing.pii import _detect_pii_impl
from app.workers.tasks.processing.rarity_external import _compute_external_rarity_impl
from app.workers.tasks.processing.rarity_internal import _compute_internal_rarity_impl
from app.workers.tasks.processing.search_index import _refresh_framework_tsvector_impl
from app.workers.tasks.processing.thumbnail import _make_thumbnail_impl


async def _process_artifact_impl(artifact_id: str) -> dict[str, Any]:
    """Run the currently implemented Artifact pipeline steps in order."""
    extraction = await _extract_text_impl(artifact_id)
    if extraction["status"] in {"missing", "failed"}:
        framework_gate = await evaluate_framework_pipeline_for_artifact(artifact_id)
        return {
            "artifact_id": artifact_id,
            "status": extraction["status"],
            "steps": {"extract": extraction, "framework_gate": framework_gate},
        }

    pii = await _detect_pii_impl(artifact_id)
    result = {
        "artifact_id": artifact_id,
        "status": pii["status"],
        "steps": {"extract": extraction, "pii": pii},
    }
    if pii["status"] != "clear":
        result["steps"]["framework_gate"] = (
            await evaluate_framework_pipeline_for_artifact(artifact_id)
        )
        return result

    metadata = await _compute_metadata_impl(artifact_id)
    minhash = await _compute_minhash_impl(artifact_id)
    rarity_internal = await _compute_internal_rarity_impl(artifact_id)
    rarity_external = await _compute_external_rarity_impl(artifact_id)
    final_rarity = await _compute_final_rarity_impl(artifact_id)
    framework_id = final_rarity.get("framework_id")
    thumbnail = (
        await _make_thumbnail_impl(str(framework_id))
        if isinstance(framework_id, str)
        else {"status": "skipped", "reason": "missing_framework"}
    )
    search_index = (
        await _refresh_framework_tsvector_impl(str(framework_id))
        if isinstance(framework_id, str)
        else {"status": "skipped", "reason": "missing_framework"}
    )
    framework_gate = await evaluate_framework_pipeline_for_artifact(artifact_id)
    return {
        "artifact_id": artifact_id,
        "status": framework_gate["framework_status"],
        "steps": {
            "extract": extraction,
            "pii": pii,
            "metadata": metadata,
            "minhash": minhash,
            "rarity_internal": rarity_internal,
            "rarity_external": rarity_external,
            "final_rarity": final_rarity,
            "thumbnail": thumbnail,
            "search_index": search_index,
            "framework_gate": framework_gate,
        },
    }
