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
        "schedule": crontab(hour=5, minute=10),
    },
    "clear-partner-commissions-hourly": {
        "task": "app.workers.tasks.developer_beat.clear_partner_commissions",
        "schedule": crontab(minute=17),
    },
    "recompute-partner-tiers-monthly": {
        "task": "app.workers.tasks.developer_beat.recompute_partner_tiers",
        "schedule": crontab(day_of_month=1, hour=4, minute=0),
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
        "schedule": crontab(hour=4, minute=30),
    },
    "process-account-deletions-hourly": {
        "task": "app.workers.tasks.gdpr_beat.process_account_deletions",
        "schedule": crontab(minute=53),
    },
    "expire-open-proposals-hourly": {
        "task": "app.workers.tasks.projects_beat.expire_open_proposals",
        "schedule": crontab(minute=32),
    },
    "expire-pending-amendments-hourly": {
        "task": "app.workers.tasks.projects_beat.expire_pending_amendments",
        "schedule": crontab(minute=35),
    },
    "escalate-disputes-hourly": {
        "task": "app.workers.tasks.projects_beat.escalate_disputes",
        "schedule": crontab(minute=26),
    },
    "auto-approve-deliverables-hourly": {
        "task": "app.workers.tasks.projects_beat.auto_approve_deliverables",
        "schedule": crontab(minute=20),
    },
    "close-expired-projects-daily": {
        "task": "app.workers.tasks.projects_beat.close_expired_projects",
        "schedule": crontab(hour=4, minute=50),
    },
    "auto-close-delivered-projects-daily": {
        "task": "app.workers.tasks.projects_beat.auto_close_delivered_projects",
        "schedule": crontab(hour=5, minute=30),
    },
    "expire-attestation-offers-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_attestation_offers",
        "schedule": crontab(minute=38),
    },
    "expire-owner-consent-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_owner_consent",
        "schedule": crontab(minute=44),
    },
    "revoke-overdue-attestations-hourly": {
        "task": "app.workers.tasks.attestation_beat.revoke_overdue_attestations",
        "schedule": crontab(minute=50),
    },
    "expire-attestation-clarifications-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_attestation_clarifications",
        "schedule": crontab(minute=41),
    },
    # Nothing else closes an unpaid fee, so an abandoned checkout would sit on
    # the requestor's dashboard forever.
    "expire-unpaid-attestation-fees-hourly": {
        "task": "app.workers.tasks.attestation_beat.expire_unpaid_attestation_fees",
        "schedule": crontab(minute=47),
    },
    "auto-release-attestations-hourly": {
        "task": "app.workers.tasks.attestation_beat.auto_release_attestations",
        "schedule": crontab(minute=23),
    },
    "escalate-attestation-disputes-hourly": {
        "task": "app.workers.tasks.attestation_beat.escalate_attestation_disputes",
        "schedule": crontab(minute=29),
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
        "schedule": crontab(minute="*/15"),
    },
    # Hourly rather than daily: the window this closes is one where a buyer has
    # paid, holds nothing, and is owed money back, so the cost of an extra pass
    # over an empty result set is worth the shorter exposure.
    "reconcile-pending-refunds-hourly": {
        "task": "app.workers.tasks.financials_beat.reconcile_pending_refunds_task",
        "schedule": crontab(minute=11),
    },
    # Escrow on the Paystack rail is commingled with the payout balance, so a
    # breach of the held-escrow floor must surface within the hour, not at
    # month-end reconciliation.
    "check-platform-balance-floor-hourly": {
        "task": "app.workers.tasks.financials_beat.check_platform_balance_floor_task",
        "schedule": crontab(minute=8),
    },
    # The floor check above asks whether money held for others is still
    # there. This asks whether what beneficiaries have already requested can
    # actually be sent: an underfunded payout retries quietly until money
    # settles, so without this nobody learns the platform is short until a
    # contributor asks why they have not been paid.
    "check-pending-payout-coverage-hourly": {
        "task": "app.workers.tasks.financials_beat.check_pending_payout_coverage_task",
        "schedule": crontab(minute=5),
    },
    # A payout whose Celery dispatch failed sits pending forever with the
    # money already claimed against the Contributor's balance; the sweep
    # re-enqueues it (the processing worker is idempotent).
    "requeue-stranded-payouts-hourly": {
        "task": "app.workers.tasks.financials_beat.requeue_stranded_payouts_task",
        "schedule": crontab(minute=2),
    },
    # A transfer Paystack holds for a one-time code produces no webhook, and
    # neither does Paystack abandoning it about an hour later. The payout would
    # sit at "processing" forever, which blocks the beneficiary from requesting
    # again and keeps the amount claimed against their balance — so an
    # unanswered code locks them out of earnings that were never sent. Runs
    # every fifteen minutes so a released beneficiary does not wait an hour.
    "reconcile-held-transfers-quarter-hourly": {
        "task": "app.workers.tasks.transfer_reconcile.reconcile_held_transfers",
        "schedule": crontab(minute="*/15"),
    },
    # Webhook rows exist for replay dedupe and short-term forensics; the
    # durable money record lives in audit_logs and the ledger, so rows past
    # retention only grow the table.
    # A crash between the provider accepting a refund and our commit leaves
    # money moved with no local record; the intent sweep asks the provider
    # directly and flags orphans. Covers Stripe, which the settlement sweeper
    # (Paystack-only) never could.
    "reconcile-refund-intents-hourly": {
        "task": "app.workers.tasks.financials_beat.reconcile_refund_intents_task",
        "schedule": crontab(minute=14),
    },
    "prune-webhook-events-daily": {
        "task": "app.workers.tasks.financials_beat.prune_webhook_events_task",
        "schedule": crontab(hour=4, minute=10),
    },
}
