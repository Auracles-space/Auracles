"""Celery Beat schedule for periodic maintenance tasks."""

from celery.schedules import crontab

from app.workers.schedules import PlatformConfigHoursSchedule

BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "snapshot-daily-analytics": {
        "task": "app.workers.tasks.admin_beat.snapshot_daily_analytics",
        "schedule": crontab(hour=0, minute=5),
    },
    "clear-expired-licenses-daily": {
        "task": "app.workers.tasks.scheduled.clear_expired_licenses",
        "schedule": 86400.0,
    },
    "clear-partner-commissions-hourly": {
        "task": "app.workers.tasks.developer_beat.clear_partner_commissions",
        "schedule": 3600.0,
    },
    "recompute-partner-tiers-monthly": {
        "task": "app.workers.tasks.developer_beat.recompute_partner_tiers",
        "schedule": 2592000.0,
    },
    "retry-partner-webhooks-minutely": {
        "task": "app.workers.tasks.partner_webhooks.retry_due_partner_webhooks",
        "schedule": 60.0,
    },
    "dispatch-saved-search-alerts-daily": {
        "task": "app.workers.tasks.saved_searches_beat.dispatch_saved_search_alerts",
        "schedule": PlatformConfigHoursSchedule(
            key="saved_search_alert_cadence_hours",
            default_hours=24,
            min_hours=1,
            max_hours=168,
        ),
    },
    "expire-gdpr-exports-daily": {
        "task": "app.workers.tasks.gdpr_beat.expire_data_exports",
        "schedule": 86400.0,
    },
    "process-account-deletions-hourly": {
        "task": "app.workers.tasks.gdpr_beat.process_account_deletions",
        "schedule": 3600.0,
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
    "expire-owner-consent-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_owner_consent",
        "schedule": 3600.0,
    },
    "revoke-overdue-attestations-hourly": {
        "task": "app.workers.tasks.attestation_beat.revoke_overdue_attestations",
        "schedule": 3600.0,
    },
    "expire-attestation-clarifications-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_attestation_clarifications",
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
    "coi-resign-reminders-daily": {
        "task": "app.workers.tasks.attestation_beat.send_coi_resign_reminders",
        "schedule": crontab(hour=2, minute=0),
    },
    "recompute-reputation-daily": {
        "task": "app.workers.tasks.reputation.recompute_reputation",
        "schedule": crontab(hour=1, minute=0),
    },
    "generate-annual-earnings-summaries-yearly": {
        "task": "app.workers.tasks.invoicing_beat.generate_annual_earnings_summaries",
        "schedule": crontab(month_of_year=1, day_of_month=2, hour=6, minute=0),
    },
    "expire-pending-org-invitations-daily": {
        "task": "app.workers.tasks.organizations_beat.expire_pending_org_invitations",
        "schedule": crontab(hour=3, minute=20),
    },
    "reap-stalled-artifacts-15min": {
        "task": "app.workers.tasks.artifacts_beat.reap_stalled_artifacts",
        "schedule": 900.0,
    },
}
