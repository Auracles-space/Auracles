"""Every scheduled task must be importable by the worker.

Beat dispatches tasks by dotted name; the worker can only execute names whose
modules appear in the Celery app's ``include`` list. A schedule entry whose
module is missing fails silently in the worst way: Beat fires on time, the
worker logs "Received unregistered task" and drops it, and the job simply never
runs. Staging caught exactly this on first boot (2026-09-02) — the
stalled-artifact reaper and org-invitation expiry were being dropped because
``artifacts_beat`` and ``organizations_beat`` were absent from ``include``.
"""

from __future__ import annotations

from pathlib import Path

from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.celery_app import create_celery_app


def test_every_scheduled_task_module_is_included() -> None:
    """Each BEAT_SCHEDULE entry's module must be in the Celery include list.

    Enforces the invariant staging's first boot found violated: a schedule
    that names a module the worker never imports is a job that silently never
    runs.
    """
    included = set(create_celery_app().conf.include)

    missing = {
        entry["task"].rsplit(".", 1)[0]
        for entry in BEAT_SCHEDULE.values()
        if entry["task"].rsplit(".", 1)[0] not in included
    }

    assert not missing, (
        f"BEAT_SCHEDULE references modules absent from celery_app include: "
        f"{sorted(missing)} — those periodic jobs are silently dropped."
    )


def test_every_task_module_on_disk_is_included() -> None:
    """Every module under app/workers/tasks/ must be in the include list.

    Wider than the schedule check: a task module that exists but is never
    imported is also invisible to `.delay()` calls from the api, not just to
    Beat. Excludes packages' __init__ and the processing/ package internals,
    which register through their own package entries.
    """
    included = set(create_celery_app().conf.include)
    tasks_dir = Path("app/workers/tasks")

    on_disk = {
        f"app.workers.tasks.{path.stem}"
        for path in tasks_dir.glob("*.py")
        if path.stem != "__init__"
    }

    missing = on_disk - included
    assert not missing, (
        f"Task modules on disk but absent from celery_app include: "
        f"{sorted(missing)} — tasks in them can be scheduled but never run."
    )
