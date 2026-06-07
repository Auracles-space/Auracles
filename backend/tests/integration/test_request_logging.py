from httpx import AsyncClient

from app.modules.health import router


async def test_request_logging_middleware_adds_request_id_header(
    client: AsyncClient, monkeypatch
) -> None:
    """Every HTTP response includes a request ID for log correlation."""

    async def healthy_components():
        return {
            "api": {"status": "ok"},
            "database": {"status": "ok"},
            "redis": {"status": "ok"},
        }

    monkeypatch.setattr(router, "run_health_checks", healthy_components)

    response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
