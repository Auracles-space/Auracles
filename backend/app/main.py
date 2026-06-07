from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
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
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.state.settings = settings
    application.include_router(admin_router, prefix="/v1")
    application.include_router(auth_router, prefix="/v1")
    application.include_router(health_router, prefix="/v1")

    return application


app = create_app()
