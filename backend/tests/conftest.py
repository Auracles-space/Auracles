import os

# Pin canonical local test values BEFORE importing anything that builds Settings.
# os.environ outranks any `.env`/`ENV_FILE`, so the suite ignores remote values a
# developer may have parked in `.env` (or selected via `ENV_FILE=.env.prod`).
# These mirror CI's service-container env so local and CI runs are identical.
os.environ.setdefault("ENVIRONMENT", "local")
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://auracles:secret@localhost:5432/auracles"
)
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["SECRET_KEY"] = "dev-only-change-me"
os.environ["TOTP_ENCRYPTION_KEY"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
os.environ["PAYOUT_ACCOUNT_ENCRYPTION_KEY"] = (
    "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
)
os.environ["PARTNER_WEBHOOK_ENCRYPTION_KEY"] = (
    "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC="
)
os.environ["S3_ARTIFACTS_BUCKET"] = "auracles-artifacts-dev"
os.environ["S3_AVATARS_BUCKET"] = "auracles-avatars-dev"
os.environ["S3_REPORTS_BUCKET"] = "auracles-reports-dev"
os.environ["S3_THUMBNAILS_BUCKET"] = "auracles-thumbnails-dev"

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from tests._guard import assert_local_datastores  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _guard_local_datastores() -> None:
    """Hard-abort the suite if resolved datastores are not local (backstop)."""
    settings = get_settings()
    try:
        assert_local_datastores(settings.database_url, settings.redis_url)
    except RuntimeError as exc:
        pytest.exit(str(exc), returncode=1)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Provide an HTTP client that exercises the FastAPI ASGI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client
