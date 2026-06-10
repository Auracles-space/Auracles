"""Celery application factory.

Builds the singleton Celery app used by both the worker and the Beat
scheduler. Broker and result backend point at Upstash Redis (db=0) via
settings; the periodic schedule comes from `beat_schedule.py`.

Maps to: TDD Section 7 (background tasks) and pre-scale infra design
Section 3.1 (worker + beat services).
"""

from celery import Celery

from app.core.config import Settings, get_settings
from app.workers.beat_schedule import BEAT_SCHEDULE


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Create the Celery app using derived Redis broker settings."""
    resolved_settings = settings or get_settings()
    celery_app = Celery(
        "auracles",
        broker=resolved_settings.celery_broker_url,
        backend=resolved_settings.celery_result_backend,
        include=[
            "app.workers.tasks.artifacts",
            "app.workers.tasks.financials",
            "app.workers.tasks.notifications",
            "app.workers.tasks.payouts",
            "app.workers.tasks.processing.blend",
            "app.workers.tasks.processing.extract",
            "app.workers.tasks.processing.metadata",
            "app.workers.tasks.processing.minhash",
            "app.workers.tasks.processing.ocr",
            "app.workers.tasks.processing.pii",
            "app.workers.tasks.processing.rarity_external",
            "app.workers.tasks.processing.rarity_internal",
            "app.workers.tasks.processing.redaction",
            "app.workers.tasks.processing.search_index",
            "app.workers.tasks.processing.thumbnail",
            "app.workers.tasks.project_notifications",
            "app.workers.tasks.projects_beat",
            "app.workers.tasks.reputation",
            "app.workers.tasks.scheduled",
            "app.workers.tasks.workspace_scan",
        ],
    )
    celery_app.conf.update(
        beat_schedule=BEAT_SCHEDULE,
        task_track_started=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
    return celery_app


app = create_celery_app()
