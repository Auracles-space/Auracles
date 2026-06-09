"""Celery Beat schedule for periodic maintenance tasks."""

BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "clear-expired-licenses-daily": {
        "task": "app.workers.tasks.scheduled.clear_expired_licenses",
        "schedule": 86400.0,
    },
}
