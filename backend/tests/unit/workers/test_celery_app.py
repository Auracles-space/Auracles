from app.core.config import Settings
from app.workers.celery_app import create_celery_app


def test_celery_app_uses_derived_redis_broker_and_backend() -> None:
    """Celery uses Redis database 0 for broker and result backend."""
    settings = Settings(REDIS_URL="redis://cache.internal:6379/4")

    celery_app = create_celery_app(settings)

    assert celery_app.conf.broker_url == "redis://cache.internal:6379/0"
    assert celery_app.conf.result_backend == "redis://cache.internal:6379/0"
