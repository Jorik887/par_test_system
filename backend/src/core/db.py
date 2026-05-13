from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text
from fastapi import HTTPException

from src.config.settings import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_use_lifo=True,
    connect_args=(
        {"timeout": 10}
        if str(settings.database_url).startswith("sqlite")
        else {"timeout": 10, "command_timeout": 60}
    ),
)

async_session_maker = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncSession:
    # Dlya sebya: vydayu session dlya zavisimostey FastAPI.
    # Pri kratkom obryve DB delayem odin retry, chtoby ne valit vse zaprosy 503.
    last_error: Exception | None = None
    for _ in range(2):
        async with async_session_maker() as session:
            try:
                await session.execute(text("SELECT 1"))
            except Exception as e:
                last_error = e
                # Sbrasivaem pool pri obryve, chtoby sleduyushchaya popytka vzyala novoe soedinenie.
                try:
                    await engine.dispose()
                except Exception:
                    pass
                continue
            # Important: after successful yield we must finish generator immediately.
            # Do not wrap yield into retry try/except, otherwise FastAPI athrow() can be swallowed.
            yield session
            return

    raise HTTPException(
        status_code=503,
        detail=f"Backend DB connection is unavailable: {last_error}",
    ) from last_error
