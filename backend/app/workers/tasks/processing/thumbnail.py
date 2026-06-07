"""Framework thumbnail generation for Artifact processing.

Thumbnails are stored as private S3 objects and referenced from the owning
Framework row. The catalog/detail APIs can later turn this key into a URL.
"""

from __future__ import annotations

import tempfile
from io import BytesIO
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
THUMBNAIL_SIZE = (400, 600)


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
            .where(Artifact.framework_id == framework_id)
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
    if artifact is not None and artifact.mime_type == PDF_MIME_TYPE:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf") as local_file:
                s3.storage.download_file(
                    settings.s3_artifacts_bucket,
                    artifact.file_key,
                    local_file.name,
                )
                thumbnail_bytes = render_pdf_thumbnail(local_file.name)
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
