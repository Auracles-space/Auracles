from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.database import Base
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.financials import models as _financials_models  # noqa: F401
from app.modules.frameworks import models as _framework_models  # noqa: F401
from app.modules.frameworks import models_artifact as _artifact_models  # noqa: F401
from app.modules.webhooks import models as _webhook_models  # noqa: F401
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
