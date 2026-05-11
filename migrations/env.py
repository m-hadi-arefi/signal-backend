from alembic import context
from sqlalchemy import engine_from_config, pool
from logging.config import fileConfig
from shared.database.base import Base
from core.config import settings

# Modles list to be imported
import shared.models.events


config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    return f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"


def run_migrations_online():
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.run_migrations_offline()
else:
    run_migrations_online()