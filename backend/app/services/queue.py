"""SQS queue service wrapping aioboto3.

M2 publishes jobs; M3 consumers will use the same service instance.
Queue and DLQ are created together with a RedrivePolicy
(maxReceiveCount=3) so messages that fail processing 3 times land in DLQ.
"""

import json
import logging
from collections.abc import Awaitable, Callable

import aioboto3

from app.config import Settings, get_settings

_log = logging.getLogger(__name__)


class QueueService:
    def __init__(
        self,
        *,
        region: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        queue_name: str,
        dlq_name: str,
    ) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._endpoint_url = endpoint_url
        self._queue_name = queue_name
        self._dlq_name = dlq_name
        self._queue_url: str | None = None
        self._dlq_url: str | None = None

    def _client(self):  # type: ignore[no-untyped-def]
        return self._session.client("sqs", endpoint_url=self._endpoint_url)

    async def ensure_queues_exist(self) -> None:
        """Create DLQ first, then main queue with RedrivePolicy pointing at DLQ."""
        async with self._client() as sqs:  # type: ignore[no-untyped-call]
            dlq_resp = await sqs.create_queue(QueueName=self._dlq_name)
            self._dlq_url = dlq_resp["QueueUrl"]
            dlq_attrs = await sqs.get_queue_attributes(
                QueueUrl=self._dlq_url, AttributeNames=["QueueArn"]
            )
            dlq_arn = dlq_attrs["Attributes"]["QueueArn"]

            main_resp = await sqs.create_queue(
                QueueName=self._queue_name,
                Attributes={
                    "RedrivePolicy": json.dumps(
                        {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}
                    ),
                    "VisibilityTimeout": "60",
                    "MessageRetentionPeriod": "1209600",
                },
            )
            self._queue_url = main_resp["QueueUrl"]

    async def _get_queue_url(self) -> str:
        if self._queue_url:
            return self._queue_url
        async with self._client() as sqs:  # type: ignore[no-untyped-call]
            resp = await sqs.get_queue_url(QueueName=self._queue_name)
            self._queue_url = resp["QueueUrl"]
            return self._queue_url

    async def publish_job(self, payload: dict[str, object]) -> str:
        url = await self._get_queue_url()
        async with self._client() as sqs:  # type: ignore[no-untyped-call]
            resp = await sqs.send_message(QueueUrl=url, MessageBody=json.dumps(payload))
            return resp["MessageId"]  # type: ignore[no-any-return]

    async def peek_messages(self, max_messages: int = 10) -> list[dict[str, object]]:
        """Read messages without deleting them (used in tests and for debugging)."""
        url = await self._get_queue_url()
        async with self._client() as sqs:  # type: ignore[no-untyped-call]
            resp = await sqs.receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=max_messages,
                VisibilityTimeout=0,
            )
            return resp.get("Messages", [])  # type: ignore[no-any-return]

    async def get_queue_attributes(self) -> dict[str, object]:
        url = await self._get_queue_url()
        async with self._client() as sqs:  # type: ignore[no-untyped-call]
            resp = await sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])
            return resp["Attributes"]  # type: ignore[no-any-return]

    async def consume_jobs(
        self,
        handler: Callable[[dict[str, object]], Awaitable[None]],
        *,
        max_messages: int = 10,
        wait_seconds: int = 20,
    ) -> None:
        """Long-poll + handle. M2 defines; M3 workers use."""
        url = await self._get_queue_url()
        async with self._client() as sqs:  # type: ignore[no-untyped-call]
            resp = await sqs.receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_seconds,
            )
            for msg in resp.get("Messages", []):
                body = json.loads(msg["Body"])
                try:
                    await handler(body)
                except Exception:
                    _log.exception("Handler failed for message %s", msg.get("MessageId"))
                    continue
                await sqs.delete_message(QueueUrl=url, ReceiptHandle=msg["ReceiptHandle"])


_instance: QueueService | None = None
_decisioning_instance: QueueService | None = None


def get_queue(settings: Settings | None = None) -> QueueService:
    global _instance
    if _instance is None:
        s = settings or get_settings()
        _instance = QueueService(
            region=s.aws_region,
            endpoint_url=s.aws_sqs_endpoint_url,
            access_key=s.aws_access_key_id,
            secret_key=s.aws_secret_access_key,
            queue_name=s.sqs_ingestion_queue,
            dlq_name=s.sqs_ingestion_dlq,
        )
    return _instance


def get_decisioning_queue(settings: Settings | None = None) -> QueueService:
    """Singleton for the pfl-decisioning-jobs queue."""
    global _decisioning_instance
    if _decisioning_instance is None:
        s = settings or get_settings()
        _decisioning_instance = QueueService(
            region=s.aws_region,
            endpoint_url=s.aws_sqs_endpoint_url,
            access_key=s.aws_access_key_id,
            secret_key=s.aws_secret_access_key,
            queue_name=s.sqs_decisioning_queue,
            dlq_name=s.sqs_decisioning_dlq,
        )
    return _decisioning_instance


def reset_queue_for_tests() -> None:
    global _instance, _decisioning_instance
    _instance = None
    _decisioning_instance = None
