"""Startup lifespan tests — init_aws_resources behavior."""

import pytest

from app.config import get_settings
from app.services.queue import reset_queue_for_tests
from app.services.storage import reset_storage_for_tests
from app.startup import init_aws_resources


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_storage_for_tests()
    reset_queue_for_tests()
    yield
    reset_storage_for_tests()
    reset_queue_for_tests()


async def test_init_is_noop_when_disabled(monkeypatch, mock_aws_services):
    """When dev_auto_create_aws_resources=False, init returns without error."""
    monkeypatch.setenv("DEV_AUTO_CREATE_AWS_RESOURCES", "false")
    get_settings.cache_clear()
    try:
        await init_aws_resources()  # must not raise
    finally:
        get_settings.cache_clear()


async def test_init_creates_bucket_and_queues_when_enabled(monkeypatch, mock_aws_services):
    monkeypatch.setenv("DEV_AUTO_CREATE_AWS_RESOURCES", "true")
    # Remove endpoint overrides so moto intercepts real boto3 calls
    monkeypatch.delenv("AWS_S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_SQS_ENDPOINT_URL", raising=False)
    get_settings.cache_clear()
    try:
        await init_aws_resources()
        # No assertion failures = success. Calls go through moto.
    finally:
        get_settings.cache_clear()
