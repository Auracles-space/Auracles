"""Framework thumbnail generation for Artifact processing.

Thumbnails are stored as private S3 objects and referenced from the owning
Framework row. The catalog/detail APIs can later turn this key into a URL.
"""

from __future__ import annotations

import tempfile
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from shutil import which
from subprocess import run
from typing import Any
from uuid import UUID

from loguru import logger
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.integrations import s3
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.workers.async_runner import run_async
from app.workers.celery_app import app

PDF_MIME_TYPE = "application/pdf"
ZIP_MIME_TYPE = "application/zip"
THUMBNAIL_SIZE = (400, 600)
ZIP_MAX_FILES = 100
ZIP_MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024
ZIP_MAX_NESTED_DEPTH = 1
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
OFFICE_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
PREVIEWABLE_SUFFIX_MIME_TYPES = {
    ".pdf": PDF_MIME_TYPE,
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".zip": ZIP_MIME_TYPE,
}


def generic_thumbnail_png() -> bytes:
    """Return a small generic PNG used when no artifact can be rendered."""
    image = Image.new("RGB", THUMBNAIL_SIZE, color=(249, 247, 242))
    draw = ImageDraw.Draw(image)
    draw.rectangle((44, 48, 356, 552), outline=(35, 35, 35), width=3)
    draw.rectangle((82, 110, 318, 132), fill=(235, 126, 61))
    draw.rectangle((82, 176, 318, 190), fill=(116, 128, 138))
    draw.rectangle((82, 226, 280, 240), fill=(116, 128, 138))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_pdf_thumbnail(path: str) -> bytes:
    """Render the first PDF page into a 400x600 PNG thumbnail."""
    from pdf2image import convert_from_path

    pages = convert_from_path(path, first_page=1, last_page=1, size=THUMBNAIL_SIZE)
    if not pages:
        return generic_thumbnail_png()
    image = pages[0].convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_image_thumbnail(path: str) -> bytes:
    """Resize an image Artifact onto the standard 400x600 thumbnail canvas."""
    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", THUMBNAIL_SIZE, color=(249, 247, 242))
        offset = (
            (THUMBNAIL_SIZE[0] - image.width) // 2,
            (THUMBNAIL_SIZE[1] - image.height) // 2,
        )
        canvas.paste(image, offset)

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def render_office_thumbnail(path: str) -> bytes:
    """Convert an Office document to PDF with LibreOffice, then render it."""
    executable = which("soffice") or which("libreoffice")
    if executable is None:
        raise RuntimeError("LibreOffice is not installed.")

    with tempfile.TemporaryDirectory() as output_dir:
        result = run(
            [
                executable,
                "--nologo",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir,
                path,
            ],
            check=False,
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError("LibreOffice failed to convert the document.")

        expected_pdf = Path(output_dir) / f"{Path(path).stem}.pdf"
        pdf_path = expected_pdf if expected_pdf.exists() else next(
            Path(output_dir).glob("*.pdf"),
            None,
        )
        if pdf_path is None:
            raise RuntimeError("LibreOffice did not produce a PDF.")
        return render_pdf_thumbnail(str(pdf_path))


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    """Return whether a ZIP member is a Unix symlink entry."""
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _validate_zip_member(info: zipfile.ZipInfo) -> PurePosixPath:
    """Validate one ZIP member path before it is extracted for preview."""
    normalized_name = info.filename.replace("\\", "/")
    member_path = PurePosixPath(normalized_name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"Unsafe ZIP member path: {info.filename}")
    if _is_zip_symlink(info):
        raise ValueError(f"Unsafe ZIP symlink member: {info.filename}")
    return member_path


def _preview_mime_for_suffix(path: PurePosixPath, archive_depth: int) -> str | None:
    """Return the previewable MIME type for a ZIP member suffix."""
    mime_type = PREVIEWABLE_SUFFIX_MIME_TYPES.get(path.suffix.lower())
    if mime_type == ZIP_MIME_TYPE and archive_depth >= ZIP_MAX_NESTED_DEPTH:
        return None
    return mime_type


def render_zip_thumbnail(path: str, archive_depth: int = 0) -> bytes:
    """Render the first safe previewable file inside a ZIP artifact."""
    with zipfile.ZipFile(path) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > ZIP_MAX_FILES:
            raise ValueError("ZIP file contains too many files.")

        uncompressed_size = 0
        with tempfile.TemporaryDirectory() as extraction_dir:
            for info in members:
                member_path = _validate_zip_member(info)
                uncompressed_size += info.file_size
                if uncompressed_size > ZIP_MAX_UNCOMPRESSED_SIZE:
                    raise ValueError("ZIP file exceeds maximum uncompressed size.")

                mime_type = _preview_mime_for_suffix(member_path, archive_depth)
                if mime_type is None:
                    continue

                local_path = Path(extraction_dir) / member_path.name
                local_path.write_bytes(archive.read(info))
                return render_artifact_thumbnail(
                    str(local_path),
                    mime_type,
                    archive_depth=archive_depth + 1,
                )

    return generic_thumbnail_png()


def render_artifact_thumbnail(
    path: str,
    mime_type: str,
    *,
    archive_depth: int = 0,
) -> bytes:
    """Render any supported Artifact type into a thumbnail PNG."""
    if mime_type == PDF_MIME_TYPE:
        return render_pdf_thumbnail(path)
    if mime_type in IMAGE_MIME_TYPES:
        return render_image_thumbnail(path)
    if mime_type in OFFICE_MIME_TYPES:
        return render_office_thumbnail(path)
    if mime_type == ZIP_MIME_TYPE:
        return render_zip_thumbnail(path, archive_depth=archive_depth)
    return generic_thumbnail_png()


async def _thumbnail_source(
    framework_id: UUID,
) -> tuple[Framework | None, Artifact | None]:
    """Return the Framework and its preferred thumbnail source Artifact."""
    async with async_session_factory() as db:
        framework = await db.get(Framework, framework_id)
        if framework is None:
            return None, None

        if framework.preview_artifact_id is not None:
            preview = await db.get(Artifact, framework.preview_artifact_id)
            if preview is not None:
                return framework, preview

        artifact = await db.scalar(
            select(Artifact)
            .where(
                Artifact.framework_id == framework_id,
                Artifact.current_for_framework.is_(True),
            )
            .order_by(Artifact.created_at.asc())
        )
        return framework, artifact


async def _make_thumbnail_impl(framework_id: str) -> dict[str, Any]:
    """Generate and upload a Framework thumbnail, then persist its S3 key."""
    parsed_framework_id = UUID(framework_id)
    framework, artifact = await _thumbnail_source(parsed_framework_id)
    if framework is None:
        return {"framework_id": framework_id, "status": "missing"}

    settings = get_settings()
    thumbnail_bytes = generic_thumbnail_png()
    if artifact is not None:
        try:
            suffix = Path(artifact.name).suffix or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix) as local_file:
                s3.storage.download_file(
                    settings.s3_artifacts_bucket,
                    artifact.file_key,
                    local_file.name,
                )
                thumbnail_bytes = render_artifact_thumbnail(
                    local_file.name,
                    artifact.mime_type,
                )
        except Exception as exc:
            logger.bind(
                module="artifacts",
                action="make_thumbnail",
                framework_id=framework_id,
                artifact_id=str(artifact.id),
            ).warning("thumbnail_render_failed", error=str(exc))

    thumbnail_key = f"frameworks/{parsed_framework_id}/thumbnail.png"
    s3.storage.upload_bytes(
        settings.s3_thumbnails_bucket,
        thumbnail_key,
        thumbnail_bytes,
        "image/png",
    )

    async with async_session_factory() as db:
        framework = await db.get(Framework, parsed_framework_id)
        if framework is None:
            return {"framework_id": framework_id, "status": "missing"}
        framework.thumbnail_key = thumbnail_key
        await db.commit()

    return {
        "framework_id": framework_id,
        "status": "thumbnail_generated",
        "thumbnail_key": thumbnail_key,
    }


@app.task(bind=True, max_retries=3)  # type: ignore[untyped-decorator]
def make_thumbnail(self: Any, framework_id: str) -> dict[str, Any]:
    """Celery wrapper for Framework thumbnail generation."""
    log = logger.bind(
        module="artifacts",
        action="make_thumbnail",
        task_id=self.request.id,
        framework_id=framework_id,
    )
    log.info("task_started")
    try:
        result = run_async(_make_thumbnail_impl(framework_id))
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60) from exc
    log.info("task_completed", result=result)
    return result
