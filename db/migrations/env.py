"""Alembic environment for APIx.

The URL is never read from alembic.ini. It comes from db.settings, which reads
the environment (and .env if present), so no credential is committed. A caller
may override it by setting the ``sqlalchemy.url`` main option on the Config
object before invoking a command - the test suite does exactly that to point
migrations at a throwaway database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from db.migrate import include_object
from db.settings import DbSettings
from schemas.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url", default=None):
    # Migrations run as the migrator role by default; the role itself is created
    # by revision 0003, so the first run on a fresh cluster is performed by the
    # superuser (scripts/init_db.py passes that URL explicitly).
    config.set_main_option("sqlalchemy.url", DbSettings.from_env().superuser_url())

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
