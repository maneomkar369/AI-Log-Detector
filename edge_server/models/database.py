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
    def _ensure_table_columns(sync_conn, table_name: str, required_columns: dict[str, str]) -> None:
        """Apply additive column upgrades for an existing table."""
        inspector = inspect(sync_conn)
        table_names = set(inspector.get_table_names())
        if table_name not in table_names:
            return

        existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            sync_conn.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            )

    def _ensure_runtime_schema(sync_conn) -> None:
        """Apply lightweight additive schema upgrades for existing installs."""
        _ensure_table_columns(
            sync_conn,
            "alerts",
            {
                "xai_explanation": "TEXT",
                "feature_vector": "TEXT",
            },
        )
        _ensure_table_columns(
            sync_conn,
            "devices",
            {
                "last_tz_offset": "INTEGER",
                "tz_shift_active_until": "TIMESTAMP",
            },
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_runtime_schema)


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
