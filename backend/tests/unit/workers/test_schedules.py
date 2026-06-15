"""Tests for custom Celery Beat schedule objects.

PersistentScheduler pickles every schedule entry to the on-disk
``celerybeat-schedule`` file, so each custom schedule must survive a
pickle round-trip. Celery's base ``schedule.__reduce__`` reconstructs via
positional ``__init__`` args, which our keyword-only constructor rejects;
these tests pin the round-trip and field preservation.
"""

from __future__ import annotations

import pickle

from app.workers.schedules import PlatformConfigHoursSchedule


def test_platform_config_schedule_survives_pickle_round_trip() -> None:
    """Beat persists schedule entries by pickling; the class must round-trip."""
    original = PlatformConfigHoursSchedule(
        key="reputation_recompute_interval_hours",
        default_hours=24,
        min_hours=2,
        max_hours=72,
        refresh_seconds=30,
    )

    restored = pickle.loads(pickle.dumps(original))

    assert isinstance(restored, PlatformConfigHoursSchedule)
    assert restored.key == "reputation_recompute_interval_hours"
    assert restored.default_hours == 24
    assert restored.min_hours == 2
    assert restored.max_hours == 72
    assert restored.refresh_seconds == 30


def test_platform_config_schedule_pickle_drops_engine() -> None:
    """The SQLAlchemy engine must not be pickled into the Beat shelve file."""
    original = PlatformConfigHoursSchedule(
        key="gdpr_purge_interval_hours",
        default_hours=12,
    )
    # Force engine creation so a non-None engine exists before pickling.
    object.__setattr__(original, "_engine", object())

    restored = pickle.loads(pickle.dumps(original))

    assert restored._engine is None
