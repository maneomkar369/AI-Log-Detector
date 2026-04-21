"""
Async SQLAlchemy Database Engine & Session
==========================================
Supports both PostgreSQL (production) and SQLite (development).
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import inspect, text

from config import settings


engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


async def init_db() -> None:
    """Create all tables if they don't exist."""
    def _ensure_alert_schema(sync_conn) -> None:
        """Apply lightweight additive schema upgrades for existing installs."""
        inspector = inspect(sync_conn)
        table_names = set(inspector.get_table_names())
        if "alerts" not in table_names:
            return

        columns = {col["name"] for col in inspector.get_columns("alerts")}
        if "xai_explanation" not in columns:
            sync_conn.execute(text("ALTER TABLE alerts ADD COLUMN xai_explanation TEXT"))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_alert_schema)


async def get_db() -> AsyncSession:
    """Dependency that yields an async DB session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
