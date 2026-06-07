from app.modules.health import service


class HealthySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def execute(self, statement):
        return None


class FailingSession(HealthySession):
    async def execute(self, statement):
        raise RuntimeError("database unavailable")


class HealthyRedis:
    async def ping(self):
        return True

    async def aclose(self):
        return None


class FailingRedis(HealthyRedis):
    async def ping(self):
        raise RuntimeError("redis unavailable")


async def test_run_health_checks_reports_all_components_ready(monkeypatch) -> None:
    """Health service reports ready when database and Redis pings succeed."""
    monkeypatch.setattr(service, "async_session_factory", lambda: HealthySession())
    monkeypatch.setattr(
        service.redis, "from_url", lambda *args, **kwargs: HealthyRedis()
    )

    checks = await service.run_health_checks()

    assert checks == {
        "api": {"status": "ok"},
        "database": {"status": "ok"},
        "redis": {"status": "ok"},
    }


async def test_run_health_checks_reports_database_failure(monkeypatch) -> None:
    """Health service reports database unavailable without leaking connection data."""
    monkeypatch.setattr(service, "async_session_factory", lambda: FailingSession())
    monkeypatch.setattr(
        service.redis, "from_url", lambda *args, **kwargs: HealthyRedis()
    )

    checks = await service.run_health_checks()

    assert checks["database"] == {
        "status": "unavailable",
        "detail": "database ping failed",
    }
    assert checks["redis"] == {"status": "ok"}


async def test_run_health_checks_reports_redis_failure(monkeypatch) -> None:
    """Health service reports Redis unavailable without leaking connection data."""
    monkeypatch.setattr(service, "async_session_factory", lambda: HealthySession())
    monkeypatch.setattr(
        service.redis, "from_url", lambda *args, **kwargs: FailingRedis()
    )

    checks = await service.run_health_checks()

    assert checks["database"] == {"status": "ok"}
    assert checks["redis"] == {
        "status": "unavailable",
        "detail": "redis ping failed",
    }
