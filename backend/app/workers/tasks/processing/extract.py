"""Text extraction step for Artifact processing.

This module turns a private S3 object into structured extraction metadata on
the `artifacts.metadata_vector` JSONB column. Later pipeline steps read that
same metadata instead of downloading the object again.
"""

from __future__ import annotations

import importlib
import re
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID
from xml.etree import ElementTree

from loguru import logger

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models_artifact import Artifact
from app.workers.async_runner import run_async
from app.workers.celery_app import app

WORD_PATTERN = re.compile(r"\b[\w'-]+\b")
OFFICE_XML_PREFIXES = ("word/", "ppt/slides/", "xl/sharedStrings.xml", "xl/worksheets/")
ZIP_MAX_FILES = 100
ZIP_MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024
ZIP_MAX_NESTED_DEPTH = 1
TINY_TEXT_WORD_THRESHOLD = 5
SUPPORTED_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".zip": "application/zip",
}
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True)
class ExtractionResult:
    """Structured text extracted from an Artifact file."""

    text: str
    headings: list[str]
    table_count: int
    word_count: int
    image_count: int
    archive_file_count: int = 0
    archive_supported_file_count: int = 0
    archive_unsupported_file_count: int = 0


def _word_count(text: str) -> int:
    """Count approximate human-readable words in extracted text."""
    return len(WORD_PATTERN.findall(text))


def _extract_with_unstructured(path: str) -> str | None:
    """Return text from `unstructured` when that optional package is available."""
    try:
        partition_module = importlib.import_module("unstructured.partition.auto")
    except ModuleNotFoundError:
        return None

    partition = partition_module.partition
    elements = partition(filename=path)
    return "\n".join(str(element) for element in elements if str(element).strip())


def _extract_pdf(path: str) -> tuple[str, int, int]:
    """Extract text plus table and image counts from a PDF file."""
    import pdfplumber

    text_parts: list[str] = []
    table_count = 0
    image_count = 0
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text:
                text_parts.append(page_text)
            table_count += len(page.find_tables())
            image_count += len(page.images)
    return "\n".join(text_parts), table_count, image_count


def _extract_office_zip(path: str) -> str:
    """Extract text nodes from Office Open XML documents without format extras."""
    text_parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.startswith(OFFICE_XML_PREFIXES):
                continue
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError:
                continue
            text_parts.extend(
                node.text.strip()
                for node in root.iter()
                if node.text is not None and node.text.strip()
            )
    return "\n".join(text_parts)


def _extract_image(path: str) -> tuple[str, int, int]:
    """Validate an image file and mark it as an OCR candidate."""
    from PIL import Image

    with Image.open(path) as image:
        image.verify()
    return "", 0, 1


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    """Return whether a ZIP member is a Unix symlink entry."""
    unix_mode = info.external_attr >> 16
    return stat.S_IFMT(unix_mode) == stat.S_IFLNK


def _validate_zip_member(info: zipfile.ZipInfo) -> PurePosixPath:
    """Validate one ZIP member path before reading any content."""
    normalized_name = info.filename.replace("\\", "/")
    member_path = PurePosixPath(normalized_name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"Unsafe ZIP member path: {info.filename}")
    if _is_zip_symlink(info):
        raise ValueError(f"Unsafe ZIP symlink member: {info.filename}")
    return member_path


def _supported_mime_for_member(
    member_path: PurePosixPath,
    archive_depth: int,
) -> str | None:
    """Return the supported MIME type for a ZIP member, if any."""
    suffix = member_path.suffix.lower()
    if suffix == ".zip" and archive_depth >= ZIP_MAX_NESTED_DEPTH:
        return None
    return SUPPORTED_MIME_BY_SUFFIX.get(suffix)


def _extract_zip(path: str, archive_depth: int) -> ExtractionResult:
    """Safely extract supported files from a ZIP Artifact container."""
    text_parts: list[str] = []
    headings: list[str] = []
    table_count = 0
    image_count = 0
    archive_file_count = 0
    archive_supported_file_count = 0
    archive_unsupported_file_count = 0
    uncompressed_size = 0

    with zipfile.ZipFile(path) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > ZIP_MAX_FILES:
            raise ValueError("ZIP file contains too many files.")

        for info in members:
            member_path = _validate_zip_member(info)
            archive_file_count += 1
            uncompressed_size += info.file_size
            if uncompressed_size > ZIP_MAX_UNCOMPRESSED_SIZE:
                raise ValueError("ZIP file exceeds maximum uncompressed size.")

            member_mime = _supported_mime_for_member(member_path, archive_depth)
            if member_mime is None:
                archive_unsupported_file_count += 1
                continue

            archive_supported_file_count += 1
            with tempfile.NamedTemporaryFile(suffix=member_path.suffix) as member_file:
                member_file.write(archive.read(info))
                member_file.flush()
                result = extract_text_from_file(
                    member_file.name,
                    member_mime,
                    archive_depth=archive_depth + 1,
                )
            if result.text:
                text_parts.append(f"--- {member_path} ---\n{result.text}")
            headings.extend(result.headings)
            table_count += result.table_count
            image_count += result.image_count
            archive_file_count += result.archive_file_count
            archive_supported_file_count += result.archive_supported_file_count
            archive_unsupported_file_count += result.archive_unsupported_file_count

    if archive_supported_file_count == 0:
        raise ValueError("ZIP file does not contain supported artifact files.")

    text = "\n\n".join(text_parts)
    return ExtractionResult(
        text=text,
        headings=headings[:20],
        table_count=table_count,
        word_count=_word_count(text),
        image_count=image_count,
        archive_file_count=archive_file_count,
        archive_supported_file_count=archive_supported_file_count,
        archive_unsupported_file_count=archive_unsupported_file_count,
    )


def _heading_candidates(text: str) -> list[str]:
    """Pick simple heading-like lines for metadata until richer parsing lands."""
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) <= 80 and (
            stripped.istitle() or stripped.isupper() or stripped.endswith(":")
        ):
            headings.append(stripped.rstrip(":"))
        if len(headings) >= 20:
            break
    return headings


def extract_text_from_file(
    path: str,
    mime_type: str,
    archive_depth: int = 0,
) -> ExtractionResult:
    """Extract text and lightweight structural metadata from an Artifact file."""
    if mime_type == "application/pdf":
        text, table_count, image_count = _extract_pdf(path)
    elif mime_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        text = _extract_with_unstructured(path) or _extract_office_zip(path)
        table_count = 0
        image_count = 0
    elif mime_type in IMAGE_MIME_TYPES:
        text, table_count, image_count = _extract_image(path)
    elif mime_type == "application/zip":
        return _extract_zip(path, archive_depth)
    else:
        text = _extract_with_unstructured(path) or ""
        table_count = 0
        image_count = 0

    return ExtractionResult(
        text=text,
        headings=_heading_candidates(text),
        table_count=table_count,
        word_count=_word_count(text),
        image_count=image_count,
    )


def _extraction_metadata(result: ExtractionResult) -> dict[str, Any]:
    """Serialize extraction output into JSONB-safe metadata."""
    empty_text = result.word_count == 0
    tiny_text = 0 < result.word_count < TINY_TEXT_WORD_THRESHOLD
    image_heavy = (
        result.image_count > 0 and result.word_count < TINY_TEXT_WORD_THRESHOLD
    )
    needs_ocr = empty_text and image_heavy
    reason_codes: list[str] = []
    if empty_text:
        reason_codes.append("empty_extraction")
    if tiny_text:
        reason_codes.append("tiny_extraction")
    if image_heavy:
        reason_codes.append("image_heavy_extraction")
    if needs_ocr:
        reason_codes.append("needs_ocr")

    return {
        "text": result.text,
        "headings": result.headings,
        "table_count": result.table_count,
        "word_count": result.word_count,
        "image_count": result.image_count,
        "archive_file_count": result.archive_file_count,
        "archive_supported_file_count": result.archive_supported_file_count,
        "archive_unsupported_file_count": result.archive_unsupported_file_count,
        "quality": {
            "empty_text": empty_text,
            "tiny_text": tiny_text,
            "image_heavy": image_heavy,
            "needs_ocr": needs_ocr,
            "low_confidence": empty_text or tiny_text or image_heavy,
            "reason_codes": reason_codes,
        },
    }


async def _mark_extraction_failed(artifact_id: UUID, error: str) -> None:
    """Persist extraction failure state and audit context."""
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, artifact_id)
        if artifact is None:
            return
        artifact.processing_status = "failed"
        await write_audit(
            db=db,
            actor_id=None,
            action="artifact_processing_failed",
            target_type="artifact",
            target_id=artifact.id,
            metadata={
                "framework_id": str(artifact.framework_id),
                "step": "extract",
                "error": error[:500],
            },
        )
        await db.commit()


async def _extract_text_impl(artifact_id: str) -> dict[str, Any]:
    """Download an Artifact, extract text, and persist metadata_vector fields."""
    parsed_artifact_id = UUID(artifact_id)
    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
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
            result = extract_text_from_file(local_file.name, mime_type)
    except Exception as exc:
        await _mark_extraction_failed(parsed_artifact_id, str(exc))
        return {"artifact_id": artifact_id, "status": "failed", "step": "extract"}

    async with async_session_factory() as db:
        artifact = await db.get(Artifact, parsed_artifact_id)
        if artifact is None:
            return {"artifact_id": artifact_id, "status": "missing"}
        metadata = dict(artifact.metadata_vector or {})
        metadata["extraction"] = _extraction_metadata(result)
        artifact.metadata_vector = metadata
        await db.commit()
    return {"artifact_id": artifact_id, "status": "extracted"}


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def extract_text(self: Any, artifact_id: str) -> dict[str, Any]:
    """Celery wrapper for Artifact text extraction."""
    log = logger.bind(
        module="artifacts",
        action="extract_text",
        task_id=self.request.id,
        artifact_id=artifact_id,
    )
    log.info("task_started")
    try:
        result = run_async(_extract_text_impl(artifact_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
