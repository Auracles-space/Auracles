from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.modules.health.router import router as health_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_format)

    application = FastAPI(
        title="Auracles API",
        version="0.1.0",
        description="API for the Auracles knowledge marketplace.",
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.include_router(health_router, prefix="/v1")

    return application


app = create_app()
