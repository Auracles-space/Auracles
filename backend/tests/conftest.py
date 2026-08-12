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
# Presigned-POST/GET signing is offline (no S3 call), but botocore still needs
# non-null credentials to build the signature. Pinned to the same dummies the
# CI job sets, so a developer with real AWS keys in their environment runs the
# suite against the same values CI does — and never against a real bucket.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
# Google connector credentials. Pinned for the same reason as the datastores:
# the Drive token-refresh path resolves `get_settings()` directly rather than
# the settings a test injects through the dependency override, so it reads
# whatever the process has. A developer with real values in `.env` sees these
# tests pass while CI, which has none, fails them on "connector is not
# configured". The values are placeholders — every request on these paths is
# mocked, so nothing authenticates against Google.
os.environ["GOOGLE_CLIENT_ID"] = "client-abc.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "gclient_secret"
os.environ["GOOGLE_DRIVE_REDIRECT_URI"] = (
    "https://auracles.space/v1/integrations/connectors/google-drive/callback"
)
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


# Tables migrations populate and tests only read. They hold reference data, not
# test fixtures: `alembic_version` tracks the schema, the two rubric tables are
# bulk-inserted by 0048, and `platform_config` by 0009. Emptying any of them
# leaves the schema at head with the data it is supposed to carry gone, which
# surfaces far from here — a rubric-less trial fixture aborts, and config
# lookups silently fall back to their code defaults, so a test asserting a
# seeded value passes or fails on which module ran before it.
#
# Anything added here must be written by a migration and never by a test. A
# table a test writes to belongs in the truncation set, or it leaks across
# modules and reintroduces exactly the interference this fixture removes.
_MIGRATION_OWNED_TABLES = (
    "alembic_version",
    "attestation_rubric_dimensions",
    "attestation_rubric_methodology",
    "platform_config",
)

# Foreign keys a preserved table points out with. Excluding a table from the
# TRUNCATE list is not enough to save it: TRUNCATE ... CASCADE empties every
# table holding a reference to one being truncated, so `platform_config` goes
# down with `users` through its `updated_by` column. Its rows are therefore
# snapshotted and reinserted, with these columns nulled — the row they pointed
# at no longer exists, and on migration-seeded rows they are null anyway.
_OUTBOUND_FK_COLUMNS = sa.text(
    "SELECT kcu.column_name "
    "FROM information_schema.table_constraints AS tc "
    "JOIN information_schema.key_column_usage AS kcu "
    "  ON kcu.constraint_name = tc.constraint_name "
    "JOIN information_schema.constraint_column_usage AS ccu "
    "  ON ccu.constraint_name = tc.constraint_name "
    "WHERE tc.constraint_type = 'FOREIGN KEY' "
    "  AND tc.table_name = :table "
    "  AND ccu.table_name <> :table"
)


@pytest.fixture(scope="module", autouse=True)
def _isolate_test_module() -> None:
    """Empty every test-written table before each test module runs.

    Test fixtures each clean up the tables their own module touches, which is
    correct in isolation but not across a full-suite run: a module that leaves
    developer, partner, or license rows behind blocks the next module's user and
    framework deletes with a foreign-key violation, and the failure surfaces in
    whichever unrelated test happens to run next.

    Rather than require every fixture to know about every other module's tables,
    each module starts from an empty database. TRUNCATE ... CASCADE ignores
    foreign-key ordering, so this stays correct as tables are added.

    Migration-owned reference data is preserved — see `_MIGRATION_OWNED_TABLES`.
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
                        "AND tablename NOT IN :preserved"
                    ).bindparams(
                        sa.bindparam(
                            "preserved",
                            value=_MIGRATION_OWNED_TABLES,
                            expanding=True,
                        )
                    )
                )
            ]
            if not tables:
                return
            snapshot = _snapshot_preserved_tables(connection)
            quoted = ", ".join(f'"{name}"' for name in tables)
            connection.execute(sa.text(f"TRUNCATE {quoted} CASCADE"))
            _restore_preserved_tables(connection, snapshot)
    finally:
        engine.dispose()


def _snapshot_preserved_tables(
    connection: sa.Connection,
) -> dict[str, list[dict[str, object]]]:
    """Read every preserved table, nulling the columns CASCADE will orphan."""
    snapshot: dict[str, list[dict[str, object]]] = {}
    for name in _MIGRATION_OWNED_TABLES:
        rows = connection.execute(sa.text(f'SELECT * FROM "{name}"')).mappings().all()
        if not rows:
            continue
        fk_columns = {
            row[0] for row in connection.execute(_OUTBOUND_FK_COLUMNS, {"table": name})
        }
        snapshot[name] = [
            {key: None if key in fk_columns else value for key, value in row.items()}
            for row in rows
        ]
    return snapshot


def _restore_preserved_tables(
    connection: sa.Connection,
    snapshot: dict[str, list[dict[str, object]]],
) -> None:
    """Reinsert snapshotted rows into any preserved table CASCADE emptied."""
    for name, rows in snapshot.items():
        still_populated = connection.execute(
            sa.text(f'SELECT 1 FROM "{name}" LIMIT 1')
        ).first()
        if still_populated:
            continue
        columns = list(rows[0])
        column_list = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join(f":{column}" for column in columns)
        connection.execute(
            sa.text(f'INSERT INTO "{name}" ({column_list}) VALUES ({placeholders})'),
            rows,
        )
