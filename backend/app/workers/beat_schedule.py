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
    "expire-pending-amendments-hourly": {
        "task": "app.workers.tasks.projects_beat.expire_pending_amendments",
        "schedule": 3600.0,
    },
    "escalate-disputes-hourly": {
        "task": "app.workers.tasks.projects_beat.escalate_disputes",
        "schedule": 3600.0,
    },
    "auto-approve-deliverables-hourly": {
        "task": "app.workers.tasks.projects_beat.auto_approve_deliverables",
        "schedule": 3600.0,
    },
    "close-expired-projects-daily": {
        "task": "app.workers.tasks.projects_beat.close_expired_projects",
        "schedule": 86400.0,
    },
    "auto-close-delivered-projects-daily": {
        "task": "app.workers.tasks.projects_beat.auto_close_delivered_projects",
        "schedule": 86400.0,
    },
    "expire-attestation-offers-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_attestation_offers",
        "schedule": 3600.0,
    },
    "revoke-overdue-attestations-hourly": {
        "task": "app.workers.tasks.attestation_beat.revoke_overdue_attestations",
        "schedule": 3600.0,
    },
    "auto-release-attestations-hourly": {
        "task": "app.workers.tasks.attestation_beat.auto_release_attestations",
        "schedule": 3600.0,
    },
    "escalate-attestation-disputes-hourly": {
        "task": "app.workers.tasks.attestation_beat.escalate_attestation_disputes",
        "schedule": 3600.0,
    },
}
