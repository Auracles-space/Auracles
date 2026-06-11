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
    assert celery_app.conf.beat_schedule["clear-partner-commissions-hourly"] == {
        "task": "app.workers.tasks.developer_beat.clear_partner_commissions",
        "schedule": 3600.0,
    }
    assert celery_app.conf.beat_schedule["recompute-partner-tiers-monthly"] == {
        "task": "app.workers.tasks.developer_beat.recompute_partner_tiers",
        "schedule": 2592000.0,
    }
    assert celery_app.conf.beat_schedule["retry-partner-webhooks-minutely"] == {
        "task": "app.workers.tasks.partner_webhooks.retry_due_partner_webhooks",
        "schedule": 60.0,
    }
