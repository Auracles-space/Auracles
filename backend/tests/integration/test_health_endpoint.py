from httpx import AsyncClient

from app.modules.health import router


async def test_health_returns_ready_when_required_components_are_reachable(
    client: AsyncClient, monkeypatch
) -> None:
    """Health readiness returns 200 when the API, database, and Redis are reachable."""

    async def healthy_components():
        return {
            "api": {"status": "ok"},
            "database": {"status": "ok"},
            "redis": {"status": "ok"},
        }

    monkeypatch.setattr(router, "run_health_checks", healthy_components)

    response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {
            "api": {"status": "ok", "detail": None},
            "database": {"status": "ok", "detail": None},
            "redis": {"status": "ok", "detail": None},
        },
    }


async def test_health_returns_unavailable_when_database_is_down(
    client: AsyncClient, monkeypatch
) -> None:
    """Health readiness returns 503 when Postgres cannot be reached."""

    async def unhealthy_database():
        return {
            "api": {"status": "ok"},
            "database": {"status": "unavailable", "detail": "connection failed"},
            "redis": {"status": "ok"},
        }

    monkeypatch.setattr(router, "run_health_checks", unhealthy_database)

    response = await client.get("/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["components"]["database"] == {
        "status": "unavailable",
        "detail": "connection failed",
    }


async def test_health_returns_unavailable_when_redis_is_down(
    client: AsyncClient, monkeypatch
) -> None:
    """Health readiness returns 503 when Redis cannot be reached."""

    async def unhealthy_redis():
        return {
            "api": {"status": "ok"},
            "database": {"status": "ok"},
            "redis": {"status": "unavailable", "detail": "ping failed"},
        }

    monkeypatch.setattr(router, "run_health_checks", unhealthy_redis)

    response = await client.get("/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["components"]["redis"] == {
        "status": "unavailable",
        "detail": "ping failed",
    }
