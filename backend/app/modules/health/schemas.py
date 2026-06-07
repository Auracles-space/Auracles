from pydantic import BaseModel, ConfigDict


class ComponentHealth(BaseModel):
    """Readiness status for a single platform component."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    """Platform readiness response for external health checks."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    components: dict[str, ComponentHealth]
