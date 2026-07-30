"""Async SQLite engine/session helpers."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from .config import get_settings

_engine = None
_sessionmaker: async_sessionmaker | None = None


def get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(
            f"sqlite+aiosqlite:///{settings.db_path}",
            connect_args={"timeout": 30},
        )
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        # create_all never ALTERs existing tables — add ownership columns by hand
        cols = {r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(project)")).fetchall()}
        if "owner_sub" not in cols:
            await conn.exec_driver_sql("ALTER TABLE project ADD COLUMN owner_sub VARCHAR")
            await conn.exec_driver_sql("ALTER TABLE project ADD COLUMN owner_name VARCHAR DEFAULT ''")
            await conn.exec_driver_sql("ALTER TABLE project ADD COLUMN shared BOOLEAN DEFAULT 0")


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        yield session
