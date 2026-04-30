"""Test fixtures.

Uses a dedicated `pfl_test` database. Each test runs inside a transaction
that's rolled back, so tests are isolated without truncating tables.

Schema is created once per session (test_engine). Each test gets its own
NullPool engine so the asyncpg connection is always bound to the current
test's event loop, avoiding "Future attached to a different loop" errors
(pytest-asyncio 0.24 with asyncio_mode=auto uses per-test loops by default).
"""

import os

# Force production-like defaults for flags whose dev-only values may bleed in
# via backend/.env. MUST happen before app.config.Settings is instantiated.
os.environ["DEV_BYPASS_MFA"] = "false"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models.base import Base

# Evict any Settings already cached by prior imports so the override above
# takes effect for this test session.
get_settings.cache_clear()

# Point tests at a separate DB
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://pfl:pfl_dev@localhost:5432/pfl_test",
)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create schema once per test session (sync wrapper for async setup).

    Uses ``DROP SCHEMA public CASCADE`` rather than ``Base.metadata.drop_all``
    so leftover tables from parallel sessions (e.g. the primary session's
    CAM-discrepancy tables that carry FKs into ``cases``) are also wiped. That
    keeps the test DB hermetic regardless of which alembic chains have touched
    it in development.
    """
    import asyncio
    import sqlalchemy as sa

    async def _create_schema():
        engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
            await conn.execute(sa.text("CREATE SCHEMA public"))
            # pgvector extension is optional — decisioning tests will skip if absent
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_create_schema())


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Per-test session in a rolled-back transaction.

    Creates a fresh NullPool engine per test so the asyncpg connection
    is always bound to the current test's event loop.
    """
    engine = create_async_engine(TEST_DB_URL, echo=False, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        Session = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with Session() as session:
            yield session
        await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db) -> AsyncClient:
    """HTTP client with DB dependency overridden to use the test session."""

    async def _get_test_session():
        yield db

    app.dependency_overrides[get_session] = _get_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_aws_services():
    """Enable moto for a test; yields the context manager."""
    with mock_aws():
        yield


@pytest_asyncio.fixture
async def storage_svc(mock_aws_services):
    from app.services.storage import StorageService

    svc = StorageService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        bucket="pfl-cases-test",
    )
    await svc.ensure_bucket_exists()
    yield svc


@pytest_asyncio.fixture
async def queue_svc(mock_aws_services):
    from app.services.queue import QueueService

    svc = QueueService(
        region="ap-south-1",
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        queue_name="pfl-ingestion-test",
        dlq_name="pfl-ingestion-test-dlq",
    )
    await svc.ensure_queues_exist()
    yield svc
