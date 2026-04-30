import json

import pytest
from moto import mock_aws

from app.services.queue import QueueService


@pytest.fixture
async def queue():
    with mock_aws():
        svc = QueueService(
            region="ap-south-1",
            endpoint_url=None,
            access_key="test",
            secret_key="test",
            queue_name="pfl-test-queue",
            dlq_name="pfl-test-queue-dlq",
        )
        await svc.ensure_queues_exist()
        yield svc


async def test_publish_returns_message_id(queue):
    msg_id = await queue.publish_job({"case_id": "abc", "loan_id": "1"})
    assert msg_id and isinstance(msg_id, str)


async def test_publish_round_trips_payload(queue):
    payload = {"case_id": "xyz", "loan_id": "10006484", "zip_s3_key": "cases/xyz/original.zip"}
    await queue.publish_job(payload)

    messages = await queue.peek_messages(max_messages=1)
    assert len(messages) == 1
    body = json.loads(messages[0]["Body"])
    assert body == payload


async def test_dlq_is_configured(queue):
    attrs = await queue.get_queue_attributes()
    assert "RedrivePolicy" in attrs
    redrive = json.loads(attrs["RedrivePolicy"])
    assert str(redrive["maxReceiveCount"]) == "3"
    assert "deadLetterTargetArn" in redrive


async def test_ensure_queues_is_idempotent(queue):
    await queue.ensure_queues_exist()
