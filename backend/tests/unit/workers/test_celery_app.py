from app.core.config import Settings
from app.workers.celery_app import create_celery_app


def test_celery_app_uses_derived_redis_broker_and_backend() -> None:
    """Celery uses Redis database 0 for broker and result backend."""
    settings = Settings(REDIS_URL="redis://cache.internal:6379/4")

    celery_app = create_celery_app(settings)

    assert celery_app.conf.broker_url == "redis://cache.internal:6379/0"
    assert celery_app.conf.result_backend == "redis://cache.internal:6379/0"


def test_celery_app_registers_developer_beat_tasks() -> None:
    """Celery includes Developer Beat tasks and schedules commission clearing."""
    settings = Settings(REDIS_URL="redis://cache.internal:6379/4")

    celery_app = create_celery_app(settings)

    assert "app.workers.tasks.developer_beat" in celery_app.conf.include
    assert "app.workers.tasks.developer_payouts" in celery_app.conf.include
    assert "app.workers.tasks.partner_webhooks" in celery_app.conf.include
    entry = celery_app.conf.beat_schedule["clear-partner-commissions-hourly"]
    assert entry["task"] == "app.workers.tasks.developer_beat.clear_partner_commissions"
    # Clock-anchored rather than an interval: beat keeps interval countdowns
    # in a file the container discards, so on Spot a restart resets them.
    assert len(entry["schedule"].minute) == 1
    monthly = celery_app.conf.beat_schedule["recompute-partner-tiers-monthly"]
    assert monthly["task"] == "app.workers.tasks.developer_beat.recompute_partner_tiers"
    # A 30-day interval was never a month and never survived a restart; the
    # first of the month is both what was meant and what beat can keep.
    assert monthly["schedule"].day_of_month == {1}
    assert celery_app.conf.beat_schedule["retry-partner-webhooks-minutely"] == {
        "task": "app.workers.tasks.partner_webhooks.retry_due_partner_webhooks",
        "schedule": 60.0,
    }


def test_celery_app_registers_admin_snapshot_beat_task() -> None:
    """Celery includes the admin Beat task and schedules the daily snapshot."""
    settings = Settings(REDIS_URL="redis://cache.internal:6379/4")

    celery_app = create_celery_app(settings)

    assert "app.workers.tasks.admin_beat" in celery_app.conf.include
    snapshot_schedule = celery_app.conf.beat_schedule["snapshot-daily-analytics"]
    assert snapshot_schedule["task"] == (
        "app.workers.tasks.admin_beat.snapshot_daily_analytics"
    )
    assert snapshot_schedule["schedule"].hour == {0}
    assert snapshot_schedule["schedule"].minute == {5}
