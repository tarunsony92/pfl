"""Async SQLAlchemy engine + session factory.

One engine per process, one session per request. The `get_session` dependency
yields a session and ensures it's closed even if a handler raises.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,  # reconnect on stale connections
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # so ORM attrs are usable post-commit in tests
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session, close on exit."""
    async with AsyncSessionLocal() as session:
        yield session
