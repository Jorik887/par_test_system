from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from src.config.settings import settings
from src.models.base import Base
import src.models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

sync_db_url = settings.database_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", sync_db_url)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    # Dlya sebya: migracionnyy shag (run migrations offline).
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Dlya sebya: migracionnyy shag (run migrations online).
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
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
    run_migrations_offline()
else:
    run_migrations_online()
