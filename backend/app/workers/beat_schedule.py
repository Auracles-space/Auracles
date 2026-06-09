"""Celery Beat schedule for periodic maintenance tasks."""

BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "clear-expired-licenses-daily": {
        "task": "app.workers.tasks.scheduled.clear_expired_licenses",
        "schedule": 86400.0,
    },
    "expire-open-proposals-hourly": {
        "task": "app.workers.tasks.projects_beat.expire_open_proposals",
        "schedule": 3600.0,
    },
    "close-expired-projects-daily": {
        "task": "app.workers.tasks.projects_beat.close_expired_projects",
        "schedule": 86400.0,
    },
}
