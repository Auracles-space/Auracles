import os

# Pin canonical local test values BEFORE importing anything that builds Settings.
# os.environ outranks any `.env`/`ENV_FILE`, so the suite ignores remote values a
# developer may have parked in `.env` (or selected via `ENV_FILE=.env.prod`).
# These mirror CI's service-container env so local and CI runs are identical.
os.environ.setdefault("ENVIRONMENT", "local")
# Dedicated test DB/Redis namespace, NEVER the dev datastores. Integration
# fixtures delete Users/audit/etc., so pointing at the `auracles` dev DB (or
# Redis db 0) would wipe the seeded dev account on every run. `auracles_test`
# and Redis db 1 are created/migrated by `make test-db` (see scripts/dev-up.sh).
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test"
)
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["SECRET_KEY"] = "dev-only-change-me"
os.environ["TOTP_ENCRYPTION_KEY"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
os.environ["PAYOUT_ACCOUNT_ENCRYPTION_KEY"] = (
    "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
)
os.environ["PARTNER_WEBHOOK_ENCRYPTION_KEY"] = (
    "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC="
)
# The suite runs on USD while the pilot deployment runs on NGN. That is
# deliberate: pinning it here keeps the existing money tests exercising the
# machinery unchanged, and any test that hardcodes a currency is then asserting
# against a known value rather than against whatever the deployment default
# happens to be. The NGN pilot configuration has its own dedicated coverage in
# tests/integration/test_ngn_pilot_settlement.py.
os.environ["PLATFORM_CURRENCY"] = "USD"
# Pinned for the same reason as the datastores above: tests that build Settings
# directly (tests/unit/test_cookies.py) otherwise inherit whatever a developer
# has in `.env`, so the suite passes or fails depending on the machine. `lax` is
# the field default those tests assert against.
os.environ["COOKIE_SAMESITE"] = "lax"
os.environ["S3_ARTIFACTS_BUCKET"] = "auracles-artifacts-dev"
os.environ["S3_AVATARS_BUCKET"] = "auracles-avatars-dev"
os.environ["S3_REPORTS_BUCKET"] = "auracles-reports-dev"
os.environ["S3_THUMBNAILS_BUCKET"] = "auracles-thumbnails-dev"

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
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


@pytest.fixture(scope="module", autouse=True)
def _isolate_test_module() -> None:
    """Empty every table before each test module runs.

    Test fixtures each clean up the tables their own module touches, which is
    correct in isolation but not across a full-suite run: a module that leaves
    developer, partner, or license rows behind blocks the next module's user and
    framework deletes with a foreign-key violation, and the failure surfaces in
    whichever unrelated test happens to run next.

    Rather than require every fixture to know about every other module's tables,
    each module starts from an empty database. TRUNCATE ... CASCADE ignores
    foreign-key ordering, so this stays correct as tables are added.

    `alembic_version` is preserved — truncating it would strand the schema.
    """
    settings = get_settings()
    engine = sa.create_engine(settings.sync_database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    sa.text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' "
                        "AND tablename <> 'alembic_version'"
                    )
                )
            ]
            if tables:
                quoted = ", ".join(f'"{name}"' for name in tables)
                connection.execute(sa.text(f"TRUNCATE {quoted} CASCADE"))
    finally:
        engine.dispose()
