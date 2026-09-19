"""Celery application factory.

Builds the singleton Celery app used by both the worker and the Beat
scheduler. Broker and result backend point at Upstash Redis (db=0) via
settings; the periodic schedule comes from `beat_schedule.py`.

Maps to: TDD Section 7 (background tasks) and pre-scale infra design
Section 3.1 (worker + beat services).
"""

from celery import Celery
from celery.signals import beat_init, celeryd_init

from app.core.config import Settings, get_settings
from app.core.observability import configure_error_tracking
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
            "app.workers.tasks.artifacts_beat",
            "app.workers.tasks.admin_beat",
            "app.workers.tasks.admin_notifications",
            "app.workers.tasks.deliverable_scan",
            "app.workers.tasks.attestation_beat",
            "app.workers.tasks.attestation_pdf",
            "app.workers.tasks.attestation_upload_scan",
            "app.workers.tasks.developer_beat",
            "app.workers.tasks.developer_payouts",
            "app.workers.tasks.financials",
            "app.workers.tasks.financials_beat",
            "app.workers.tasks.invoicing",
            "app.workers.tasks.invoicing_beat",
            "app.workers.tasks.gdpr_beat",
            "app.workers.tasks.kyc_document_scan",
            "app.workers.tasks.kyc_notifications",
            "app.workers.tasks.notifications",
            "app.workers.tasks.org_notifications",
            "app.workers.tasks.organizations_beat",
            "app.workers.tasks.partner_webhooks",
            "app.workers.tasks.payouts",
            "app.workers.tasks.transfer_reconcile",
            "app.workers.tasks.platform_withdrawals",
            "app.workers.tasks.provider_fee_backfill",
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
            "app.workers.tasks.saved_searches_beat",
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


@celeryd_init.connect  # type: ignore[untyped-decorator]  # celery signal.connect is untyped
def _init_worker_error_tracking(**_kwargs: object) -> None:
    """Start error tracking in each worker process.

    Wired to the signal rather than to module import because the SDK must be
    initialised after Celery forks; a client created in the parent does not
    survive into the children intact.
    """
    configure_error_tracking(get_settings())


@beat_init.connect  # type: ignore[untyped-decorator]  # celery signal.connect is untyped
def _init_beat_error_tracking(**_kwargs: object) -> None:
    """Start error tracking in the Beat process.

    Beat is a separate process from the workers and receives neither
    ``celeryd_init`` nor the API's startup path, so without this its failures
    would be the only ones nobody hears about.
    """
    configure_error_tracking(get_settings())


app = create_celery_app()
