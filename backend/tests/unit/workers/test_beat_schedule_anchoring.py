"""Tests that infrequent scheduled work is anchored to the clock.

Celery Beat counts a plain interval from the moment it starts, and it keeps
the countdown in a file on the container filesystem — which Fargate discards
on every restart. Beat also runs on Spot. So an interval schedule restarts
its countdown each time the task is replaced, and a run of restarts closer
together than the interval starves the task completely, silently, with no
error anywhere.

That is not theoretical: on 2026-09-19 two beat restarts seven minutes apart
delayed the transfer reconciler, and the same mechanism would have starved it
outright had the restarts kept up. The tasks most exposed are the least
frequent ones, and on this platform they are the ones that settle money.

A crontab schedule is computed from the wall clock instead, so a restart
costs at most the remainder of the current window and never compounds.
"""

from __future__ import annotations

from celery.schedules import crontab

from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.schedules import PlatformConfigHoursSchedule

# Below this, a plain interval is fine: beat would have to be restarting
# every few minutes for a run to be missed, and that is a different failure
# with louder symptoms than a quietly skipped task.
INTERVAL_CEILING_SECONDS = 600


def test_infrequent_tasks_are_anchored_to_the_clock_not_to_boot() -> None:
    """Anything running less often than every ten minutes uses a crontab.

    An interval schedule resets on every beat restart, so on Spot the
    reconciler, the balance checks and the expiry sweeps could each go a full
    day without running while every log line looked healthy.
    """
    boot_anchored = {
        name: entry["schedule"]
        for name, entry in BEAT_SCHEDULE.items()
        if isinstance(entry["schedule"], int | float)
        and entry["schedule"] > INTERVAL_CEILING_SECONDS
    }

    assert boot_anchored == {}


def test_every_entry_has_a_schedule_of_a_supported_kind() -> None:
    """Guard the assumption the check above relies on.

    If an entry carried some other schedule object, the check would pass by
    ignoring it rather than by the task being safe.
    """
    for name, entry in BEAT_SCHEDULE.items():
        schedule = entry["schedule"]
        assert isinstance(
            schedule, crontab | PlatformConfigHoursSchedule | int | float
        ), f"{name} carries an unrecognized schedule type"


def test_hourly_money_tasks_do_not_all_fire_on_the_hour() -> None:
    """Hourly work is spread across the hour rather than stampeding at :00.

    These tasks query the same database and several call Paystack. Firing
    them together makes one busy minute an outage-shaped spike, and a
    provider rate limit would take out the money checks as a group rather
    than one at a time.
    """
    minutes = [
        sorted(entry["schedule"].minute)[0]
        for name, entry in BEAT_SCHEDULE.items()
        if name.endswith("-hourly") and isinstance(entry["schedule"], crontab)
    ]

    assert len(minutes) > 1
    assert len(set(minutes)) > 1, "every hourly task fires in the same minute"
