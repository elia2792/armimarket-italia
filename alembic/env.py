import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import settings
from app.models.base import Base

# Import di tutti i modelli per popolare i metadati di autogenerate
import app.models.user  # noqa: F401
import app.models.geo  # noqa: F401
import app.models.annuncio  # noqa: F401
import app.models.poligono  # noqa: F401
import app.models.preferito  # noqa: F401
import app.models.email_log  # noqa: F401
import app.models.password_reset  # noqa: F401
import app.models.ricerca_salvata  # noqa: F401
import app.models.segnalazione  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    """Recupera la stringa di connessione database dalle impostazioni applicative."""
    url = settings.DATABASE_URL
    if url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://")
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


def run_migrations_offline() -> None:
    """Esecuzione migrazioni in modalità 'offline'."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Esecuzione asincrona delle migrazioni con SQLAlchemy 2.x asyncpg / aiosqlite."""
    url = get_url()
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Esecuzione migrazioni in modalità 'online'."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
