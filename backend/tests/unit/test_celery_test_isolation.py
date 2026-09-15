"""The test suite must never publish background tasks to the local worker.

The worker serves the dev database, so a task enqueued by code under test (an
admin review notice, a notification fan-out) used to land as real rows for the
seeded dev accounts, e.g. "project dispute" notices nobody raised.
"""


def test_tests_publish_to_an_in_memory_broker() -> None:
    """Enqueued tasks go to an in-memory transport nothing consumes."""
    from app.workers.celery_app import app

    assert app.conf.broker_url == "memory://"
