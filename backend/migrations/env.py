"""Alembic environment: uses the app's DATABASE_URL and model metadata."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app import models  # noqa: F401  (registers tables)
from app.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True,
                      compare_type=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            # Several API pods start at once; only one may migrate at a time.
            conn.execute(text("SELECT pg_advisory_lock(727274)"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True,
                          render_as_batch=conn.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
