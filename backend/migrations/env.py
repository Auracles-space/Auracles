from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.database import Base
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.attestation import models as _attestation_models  # noqa: F401
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.collections import models as _collection_models  # noqa: F401
from app.modules.developer import models as _developer_models  # noqa: F401
from app.modules.financials import models as _financials_models  # noqa: F401
from app.modules.frameworks import models as _framework_models  # noqa: F401
from app.modules.frameworks import models_artifact as _artifact_models  # noqa: F401
from app.modules.gdpr import models as _gdpr_models  # noqa: F401
from app.modules.integrations import models as _integration_models  # noqa: F401
from app.modules.invoicing import models as _invoicing_models  # noqa: F401
from app.modules.notifications import models as _notification_models  # noqa: F401
from app.modules.organizations import models as _organization_models  # noqa: F401
from app.modules.projects import models as _project_models  # noqa: F401
from app.modules.reputation import models as _reputation_models  # noqa: F401
from app.modules.saved_searches import models as _saved_search_models  # noqa: F401
from app.modules.waitlist import models as _waitlist_models  # noqa: F401
from app.modules.webhooks import models as _webhook_models  # noqa: F401
from app.modules.workspace import models as _workspace_models  # noqa: F401
from app.shared.models import audit_log as _audit_log_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""
    settings = get_settings()
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    settings = get_settings()
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
