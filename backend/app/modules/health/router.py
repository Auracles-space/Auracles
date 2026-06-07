from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.modules.health.schemas import ComponentHealth, HealthResponse
from app.modules.health.service import run_health_checks

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    summary="Check platform readiness",
    description=(
        "Reports API, database, and Redis readiness for platform health checks."
    ),
)
async def get_health() -> HealthResponse | JSONResponse:
    """Return platform readiness for API, database, and Redis."""
    checks = await run_health_checks()
    components = {
        name: ComponentHealth(**component) for name, component in checks.items()
    }
    status = (
        "ok"
        if all(component.status == "ok" for component in components.values())
        else "unhealthy"
    )
    payload = HealthResponse(status=status, components=components)

    if status != "ok":
        return JSONResponse(status_code=503, content=payload.model_dump())

    return payload
