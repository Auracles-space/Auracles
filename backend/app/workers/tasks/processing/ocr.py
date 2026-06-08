"""OCR step for scanned and image-heavy Artifact processing.

The extraction step identifies Artifacts whose readable text is missing but
whose file appears image-heavy. This module fills that gap with local Tesseract
OCR, then updates the same `metadata_vector.extraction` block consumed by PII,
metadata, fingerprinting, and rarity workers.
"""

from __future__ import annotations

import csv
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models_artifact import Artifact
from app.workers.async_runner import run_async
from app.workers.celery_app import app

WORD_PATTERN = re.compile(r"\b[\w'-]+\b")
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
TINY_TEXT_WORD_THRESHOLD = 5
LOW_OCR_CONFIDENCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class OcrPageResult:
    """OCR result for one rendered page or standalone image."""

    page_number: int
    text: str
    confidence: float | None


@dataclass(frozen=True)
class OcrResult:
    """OCR text and confidence summary for an Artifact file."""

    text: str
    engine: str
    confidence: float | None
    pages: list[OcrPageResult]


class OcrError(RuntimeError):
    """Base OCR failure that should be recorded instead of hard-failing."""


class UnsupportedOcrFileError(OcrError):
    """Raised when a MIME type cannot be OCR-processed by this adapter."""


class TesseractUnavailableError(OcrError):
    """Raised when the configured Tesseract binary is unavailable."""


def _word_count(text: str) -> int:
    """Count approximate human-readable words in OCR text."""
    return len(WORD_PATTERN.findall(text))


def _should_run_ocr(metadata: dict[str, Any], force: bool = False) -> bool:
    """Return whether Artifact metadata asks for OCR."""
    if force:
        return True
    extraction = metadata.get("extraction") or {}
    quality = extraction.get("quality") or {}
    return bool(quality.get("needs_ocr"))


def _average(values: list[float]) -> float | None:
    """Return an average rounded for stable JSON metadata."""
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _normalise_reason_codes(
    *,
    word_count: int,
    image_count: int,
    confidence: float | None,
) -> tuple[dict[str, Any], list[str]]:
    """Build quality flags after OCR has replaced the extraction text."""
    empty_text = word_count == 0
    tiny_text = 0 < word_count < TINY_TEXT_WORD_THRESHOLD
    image_heavy = image_count > 0 and word_count < TINY_TEXT_WORD_THRESHOLD
    needs_ocr = empty_text and image_heavy
    low_ocr_confidence = (
        confidence is not None and confidence < LOW_OCR_CONFIDENCE_THRESHOLD
    )
    low_confidence = empty_text or tiny_text or image_heavy or low_ocr_confidence
    reason_codes: list[str] = []
    if empty_text:
        reason_codes.append("empty_extraction")
    if tiny_text:
        reason_codes.append("tiny_extraction")
    if image_heavy:
        reason_codes.append("image_heavy_extraction")
    if needs_ocr:
        reason_codes.append("needs_ocr")
    if low_ocr_confidence:
        reason_codes.append("low_ocr_confidence")
    if not needs_ocr and not empty_text:
        reason_codes.append("ocr_applied")

    return (
        {
            "empty_text": empty_text,
            "tiny_text": tiny_text,
            "image_heavy": image_heavy,
            "needs_ocr": needs_ocr,
            "low_confidence": low_confidence,
            "reason_codes": reason_codes,
        },
        reason_codes,
    )


def merge_ocr_result(metadata: dict[str, Any], result: OcrResult) -> dict[str, Any]:
    """Return metadata with OCR text replacing the prior OCR extraction block."""
    updated = dict(metadata)
    extraction = dict(updated.get("extraction") or {})
    base_text = extraction.get("pre_ocr_text")
    if base_text is None:
        base_text = "" if extraction.get("ocr_applied") else extraction.get("text", "")
    combined_text = "\n\n".join(part for part in [base_text, result.text] if part)
    word_count = _word_count(combined_text)
    image_count = int(extraction.get("image_count") or len(result.pages))
    quality, _ = _normalise_reason_codes(
        word_count=word_count,
        image_count=image_count,
        confidence=result.confidence,
    )
    extraction.update(
        {
            "text": combined_text,
            "pre_ocr_text": base_text,
            "ocr_text": result.text,
            "ocr_applied": bool(result.text),
            "ocr_failed": False,
            "ocr_engine": result.engine,
            "ocr_confidence": result.confidence,
            "ocr_pages": [
                {
                    "page_number": page.page_number,
                    "confidence": page.confidence,
                    "word_count": _word_count(page.text),
                }
                for page in result.pages
            ],
            "word_count": word_count,
            "quality": quality,
        }
    )
    updated["extraction"] = extraction
    return updated


def mark_ocr_failed(metadata: dict[str, Any], reason: str) -> dict[str, Any]:
    """Return metadata with an OCR failure reason recorded for review gates."""
    updated = dict(metadata)
    extraction = dict(updated.get("extraction") or {})
    quality = dict(extraction.get("quality") or {})
    reason_codes = [
        code
        for code in quality.get("reason_codes", [])
        if code not in {"needs_ocr", "ocr_applied", "ocr_failed"}
    ]
    if "ocr_failed" not in reason_codes:
        reason_codes.append("ocr_failed")
    quality["needs_ocr"] = False
    quality["low_confidence"] = True
    quality["reason_codes"] = reason_codes
    extraction.update(
        {
            "ocr_applied": False,
            "ocr_failed": True,
            "ocr_failure_reason": reason[:500],
            "quality": quality,
        }
    )
    updated["extraction"] = extraction
    return updated


def _parse_tesseract_tsv(tsv_output: str) -> tuple[str, float | None]:
    """Extract readable text and average confidence from Tesseract TSV output."""
    words: list[str] = []
    confidences: list[float] = []
    reader = csv.DictReader(tsv_output.splitlines(), delimiter="\t")
    for row in reader:
        text = (row.get("text") or "").strip()
        if text:
            words.append(text)
        try:
            confidence = float(row.get("conf") or -1)
        except ValueError:
            continue
        if confidence >= 0:
            confidences.append(confidence / 100)
    return " ".join(words), _average(confidences)


def _ocr_image_path(path: str, page_number: int) -> OcrPageResult:
    """Run local Tesseract on one image path and return page-level metadata."""
    settings = get_settings()
    command = [
        settings.ocr_tesseract_command,
        path,
        "stdout",
        "--psm",
        settings.ocr_tesseract_page_segmentation_mode,
        "tsv",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.ocr_timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise TesseractUnavailableError("Tesseract binary is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise OcrError("Tesseract OCR timed out.") from exc
    except subprocess.CalledProcessError as exc:
        raise OcrError((exc.stderr or "Tesseract OCR failed.").strip()) from exc

    text, confidence = _parse_tesseract_tsv(completed.stdout)
    return OcrPageResult(page_number=page_number, text=text, confidence=confidence)


def extract_ocr_text_from_file(path: str, mime_type: str) -> OcrResult:
    """Run local Tesseract OCR for image files and PDFs."""
    if mime_type in IMAGE_MIME_TYPES:
        page = _ocr_image_path(path, page_number=1)
        return OcrResult(
            text=page.text,
            engine="tesseract",
            confidence=page.confidence,
            pages=[page],
        )
    if mime_type != "application/pdf":
        raise UnsupportedOcrFileError(f"OCR is unsupported for MIME type {mime_type}.")

    from pdf2image import convert_from_path

    settings = get_settings()
    pages: list[OcrPageResult] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            images = convert_from_path(path, dpi=settings.ocr_pdf_dpi)
        except Exception as exc:
            raise OcrError("PDF rendering for OCR failed.") from exc
        for index, image in enumerate(images, start=1):
            page_path = str(Path(temp_dir) / f"page-{index}.png")
            image.save(page_path, format="PNG")
            pages.append(_ocr_image_path(page_path, page_number=index))

    text = "\n\n".join(page.text for page in pages if page.text)
    confidence = _average(
        [page.confidence for page in pages if page.confidence is not None]
    )
    return OcrResult(
        text=text,
        engine="tesseract",
        confidence=confidence,
        pages=pages,
    )


async def _run_ocr_if_needed_impl(
    artifact_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Apply OCR when extraction metadata marks the Artifact as needing OCR."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        metadata = dict(artifact.metadata_vector or {})
        if not _should_run_ocr(metadata, force=force):
            return {"artifact_id": artifact_id, "status": "skipped"}
        file_key = artifact.file_key
        mime_type = artifact.mime_type

    settings = get_settings()
    try:
        with tempfile.NamedTemporaryFile() as local_file:
            s3.storage.download_file(
                settings.s3_artifacts_bucket,
                file_key,
                local_file.name,
            )
            result = extract_ocr_text_from_file(local_file.name, mime_type)
    except OcrError as exc:
        async with async_session_factory() as db:
            artifact = await db.get(Artifact, parsed_artifact_id)
            if artifact is None:
                return {"artifact_id": artifact_id, "status": "missing"}
            artifact.metadata_vector = mark_ocr_failed(
                dict(artifact.metadata_vector or {}),
                str(exc),
            )
            await db.commit()
        return {
            "artifact_id": artifact_id,
            "status": "ocr_failed",
            "reason": str(exc)[:500],
        }

    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        artifact.metadata_vector = merge_ocr_result(
            dict(artifact.metadata_vector or {}),
            result,
        )
        await db.commit()

    return {
        "artifact_id": artifact_id,
        "status": "ocr_applied" if result.text else "ocr_empty",
        "confidence": result.confidence,
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def run_ocr(self: Any, artifact_id: str, force: bool = False) -> dict[str, Any]:
    """Celery wrapper for Artifact OCR processing."""
    log = logger.bind(
        module="artifacts",
        action="run_ocr",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_run_ocr_if_needed_impl(artifact_id, force=force))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
