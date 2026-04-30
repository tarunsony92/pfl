"""Dev-only startup hooks: create bucket + queue if missing.

Production uses CDK (M8) to provision real AWS resources, so this is a no-op
when `dev_auto_create_aws_resources=False`.
"""

import logging

from app.config import get_settings
from app.services.email import get_email_service
from app.services.queue import get_queue
from app.services.storage import get_storage

_log = logging.getLogger(__name__)


async def init_aws_resources() -> None:
    settings = get_settings()
    if not settings.dev_auto_create_aws_resources:
        _log.info("Skipping AWS resource init (dev_auto_create_aws_resources=False)")
        return

    storage = get_storage(settings)
    await storage.ensure_bucket_exists()
    _log.info("Ensured bucket: %s", settings.s3_bucket)

    queue = get_queue(settings)
    await queue.ensure_queues_exist()
    _log.info("Ensured queues: %s, %s", settings.sqs_ingestion_queue, settings.sqs_ingestion_dlq)

    if settings.ses_verify_on_startup:
        email = get_email_service(settings)
        try:
            await email.verify_sender_identity()
            _log.info("Verified SES sender: %s", email.sender)
        except Exception:
            _log.warning(
                "SES sender verification failed for %s (LocalStack may be flaky — continuing)",
                settings.ses_sender,
                exc_info=True,
            )
