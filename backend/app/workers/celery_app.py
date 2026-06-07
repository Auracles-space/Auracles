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
            "app.workers.tasks.notifications",
            "app.workers.tasks.payouts",
            "app.workers.tasks.reputation",
            "app.workers.tasks.scheduled",
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
