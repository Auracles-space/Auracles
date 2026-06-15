"""Custom Celery Beat schedule helpers.

Contains schedule objects that need live platform configuration while keeping
Beat entries declarative in `beat_schedule.py`.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, cast

from celery.schedules import schedule
from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.financials.models import PlatformConfig


def _rebuild_platform_config_schedule(
    cls: type[PlatformConfigHoursSchedule],
) -> PlatformConfigHoursSchedule:
    """Create a bare instance for unpickling; state is applied via __setstate__."""
    return cls.__new__(cls)


class PlatformConfigHoursSchedule(schedule):  # type: ignore[misc]  # celery's `schedule` is untyped (Any)
    """Celery schedule backed by an integer `platform_config` hour value.

    The value is cached briefly because Celery Beat calls `is_due` frequently.
    Invalid or missing config safely falls back to the default cadence.
    """

    def __init__(
        self,
        *,
        key: str,
        default_hours: int,
        min_hours: int = 1,
        max_hours: int = 168,
        refresh_seconds: int = 60,
        **kwargs: Any,
    ) -> None:
        """Create a config-backed schedule with fallback bounds."""
        self.key = key
        self.default_hours = default_hours
        self.min_hours = min_hours
        self.max_hours = max_hours
        self.refresh_seconds = refresh_seconds
        self._engine: Engine | None = None
        self._cache_expires_at = 0.0
        super().__init__(
            run_every=timedelta(hours=default_hours),
            **kwargs,
        )

    def __getstate__(self) -> dict[str, Any]:
        """Exclude the SQLAlchemy engine when Celery Beat persists schedule state."""
        state = dict(self.__dict__)
        state["_engine"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore pickled state directly, bypassing the keyword-only __init__."""
        self.__dict__.update(state)

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle via state, not positional args.

        Celery's base ``schedule.__reduce__`` reconstructs with positional
        ``(run_every, relative, nowfun, app)`` args, which this class's
        keyword-only constructor rejects. Rebuild without calling ``__init__``
        and let ``__setstate__`` restore every field instead.
        """
        return (_rebuild_platform_config_schedule, (type(self),), self.__getstate__())

    def _get_engine(self) -> Engine:
        """Return a lazily-created sync engine for Beat's sync process."""
        if self._engine is None:
            self._engine = create_engine(
                get_settings().sync_database_url,
                pool_pre_ping=True,
            )
        return self._engine

    def _hours_from_config(self) -> int:
        """Load and validate the configured cadence, falling back on errors."""
        try:
            with Session(self._get_engine()) as session:
                raw_value = session.scalar(
                    select(PlatformConfig.value).where(PlatformConfig.key == self.key)
                )
        except Exception as exc:  # pragma: no cover - defensive Beat fallback
            logger.bind(
                module="workers",
                action="load_platform_config_schedule",
                config_key=self.key,
            ).warning("platform_config_schedule_load_failed", error=str(exc))
            return self.default_hours

        try:
            hours = int(str(raw_value or self.default_hours).strip())
        except ValueError:
            return self.default_hours

        if hours < self.min_hours or hours > self.max_hours:
            return self.default_hours
        return hours

    def _refresh_run_every(self) -> None:
        """Refresh `run_every` from platform config when the cache expires."""
        now = time.monotonic()
        if now < self._cache_expires_at:
            return
        self.run_every = timedelta(hours=self._hours_from_config())
        self._cache_expires_at = now + self.refresh_seconds

    def is_due(self, last_run_at: Any) -> tuple[bool, float]:
        """Return whether the task is due using the latest cached cadence."""
        self._refresh_run_every()
        # celery's untyped `schedule.is_due` returns a `schedstate(is_due, next)`
        # namedtuple that unpacks as (bool, float); mypy only sees Any.
        return cast("tuple[bool, float]", super().is_due(last_run_at))
