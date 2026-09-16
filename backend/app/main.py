from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.observability import configure_error_tracking
from app.core.redis import close_redis
from app.integrations.s3 import verify_object_storage
from app.modules.admin.org_detail_router import router as admin_org_detail_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.treasury_router import router as admin_treasury_router
from app.modules.attestation.router import router as attestation_router
from app.modules.auth.router import router as auth_router
from app.modules.collections.router import router as collections_router
from app.modules.developer.auth import PartnerApiRequestLoggingMiddleware
from app.modules.developer.partner_router import router as partner_router
from app.modules.developer.router import router as developer_router
from app.modules.explore.router import router as explore_router
from app.modules.financials.router import router as financials_router
from app.modules.frameworks.router import (
    org_router as org_frameworks_router,
)
from app.modules.frameworks.router import router as frameworks_router
from app.modules.gdpr.router import router as gdpr_router
from app.modules.health.router import router as health_router
from app.modules.integrations.router import router as integrations_router
from app.modules.library.router import router as library_router
from app.modules.notifications.router import router as notifications_router
from app.modules.organizations.router import (
    admin_org_attestor_router,
    admin_orgs_router,
)
from app.modules.organizations.router import (
    invitation_router as org_invitation_router,
)
from app.modules.organizations.router import (
    public_router as contributor_orgs_router,
)
from app.modules.organizations.router import (
    router as organizations_router,
)
from app.modules.profiles.router import router as profiles_router
from app.modules.projects.router import org_router as org_projects_router
from app.modules.projects.router import router as projects_router
from app.modules.realtime.gateway import router as realtime_router
from app.modules.reputation.router import router as reputation_router
from app.modules.saved_searches.router import router as saved_searches_router
from app.modules.settings.router import router as settings_router
from app.modules.waitlist.router import router as waitlist_router
from app.modules.webhooks.router import router as webhooks_router
from app.modules.workspace.router import router as workspace_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Verify storage credentials at boot, then close clients on shutdown."""
    del application
    # Fail the deploy loudly if AWS creds are a mismatched pair, rather than
    # silently 403-ing every presigned artifact upload. Skipped in local.
    verify_object_storage(get_settings())
    try:
        yield
    finally:
        await close_redis()
        await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_format)
    # After logging, because the CRITICAL forwarding sink attaches to loguru.
    configure_error_tracking(settings)

    application = FastAPI(
        title="Auracles API",
        version="0.1.0",
        description="API for the Auracles knowledge marketplace.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(PartnerApiRequestLoggingMiddleware)
    application.state.settings = settings
    application.include_router(admin_router, prefix="/v1")
    application.include_router(attestation_router, prefix="/v1")
    application.include_router(auth_router, prefix="/v1")
    application.include_router(collections_router, prefix="/v1")
    application.include_router(developer_router, prefix="/v1")
    application.include_router(explore_router, prefix="/v1")
    application.include_router(financials_router, prefix="/v1")
    application.include_router(frameworks_router, prefix="/v1")
    application.include_router(org_frameworks_router, prefix="/v1")
    application.include_router(gdpr_router, prefix="/v1")
    application.include_router(integrations_router, prefix="/v1")
    application.include_router(library_router, prefix="/v1")
    application.include_router(notifications_router, prefix="/v1")
    application.include_router(organizations_router, prefix="/v1")
    application.include_router(contributor_orgs_router, prefix="/v1")
    application.include_router(org_invitation_router, prefix="/v1")
    application.include_router(admin_orgs_router, prefix="/v1")
    application.include_router(admin_org_detail_router, prefix="/v1")
    application.include_router(admin_org_attestor_router, prefix="/v1")
    application.include_router(admin_treasury_router, prefix="/v1")
    application.include_router(profiles_router, prefix="/v1")
    application.include_router(projects_router, prefix="/v1")
    application.include_router(org_projects_router, prefix="/v1")
    application.include_router(partner_router, prefix="/v1")
    application.include_router(realtime_router, prefix="/v1")
    application.include_router(reputation_router, prefix="/v1")
    application.include_router(saved_searches_router, prefix="/v1")
    application.include_router(settings_router, prefix="/v1")
    application.include_router(waitlist_router, prefix="/v1")
    application.include_router(webhooks_router, prefix="/v1")
    application.include_router(workspace_router, prefix="/v1")
    application.include_router(health_router, prefix="/v1")

    return application


app = create_app()
