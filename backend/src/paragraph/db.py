from __future__ import annotations

from typing import Dict, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from src.config.settings import settings
from src.core.db import get_session
from src.services.targets import resolve_runtime_target, resolve_target_id_from_request

Base = declarative_base()

_session_makers: Dict[str, async_sessionmaker[AsyncSession]] = {}
_default_session_maker: Optional[async_sessionmaker[AsyncSession]] = None


def _build_default_sessionmaker() -> Optional[async_sessionmaker[AsyncSession]]:
    # Dlya sebya: staryy kod importit AsyncSessionLocal napryamuyu, poetomu derzhim default-factory.
    dsn = (settings.paragraph_db_dsn or "").strip()
    if not dsn:
        return None
    engine = create_async_engine(
        dsn,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_use_lifo=True,
        connect_args={
            "timeout": 10,
            "command_timeout": 60,
        },
    )
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


_default_session_maker = _build_default_sessionmaker()


def _get_or_create_sessionmaker(dsn: str) -> async_sessionmaker[AsyncSession]:
    # Dlya sebya: per dsn derzhim odin sessionmaker, chtoby ne sozdavat engine na kazhdom zaprose.
    maker = _session_makers.get(dsn)
    if maker is not None:
        return maker

    engine = create_async_engine(
        dsn,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_use_lifo=True,
        connect_args={
            "timeout": 10,
            "command_timeout": 60,
        },
    )
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    _session_makers[dsn] = maker
    return maker


def get_paragraph_sessionmaker_by_dsn(dsn: str) -> async_sessionmaker[AsyncSession]:
    # Dlya sebya: public helper dlya pereispol'zovaniya cache engine/sessionmaker po DSN.
    normalized = (dsn or "").strip()
    if not normalized:
        raise RuntimeError("Paragraph DB DSN is empty")
    return _get_or_create_sessionmaker(normalized)


def AsyncSessionLocal() -> AsyncSession:
    # Dlya sebya: backward-compat shim dlya staryh importov (repository/tests).
    if _default_session_maker is None:
        raise RuntimeError("PARAGRAPH_DB_DSN is not configured for AsyncSessionLocal")
    return _default_session_maker()


async def get_paragraph_session(
    request: Request,
    backend_session: AsyncSession = Depends(get_session),
) -> AsyncSession:
    # Dlya sebya: paragraph DB berem iz target profile (esli target zadan), inache iz .env.
    target_id = resolve_target_id_from_request(request)
    runtime_target = await resolve_runtime_target(backend_session, target_id)
    dsn = runtime_target.paragraph_db_dsn or settings.paragraph_db_dsn
    if not dsn:
        raise HTTPException(
            status_code=400,
            detail="Paragraph DB DSN is not configured for selected target and .env fallback",
        )

    maker = _get_or_create_sessionmaker(dsn)
    async with maker() as paragraph_session:
        try:
            # Dlya sebya: daem ponyatnuyu 502, esli profil ukazyvaet na nedostupnuyu Paragraph DB.
            await paragraph_session.execute(text("SELECT 1"))
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot connect to Paragraph DB for selected target: {e}",
            ) from e
        yield paragraph_session
