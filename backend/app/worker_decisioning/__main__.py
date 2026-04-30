"""python -m app.worker_decisioning — consumes pfl-decisioning-jobs SQS messages."""
import asyncio
import logging
from uuid import UUID

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.decisioning.engine import run_phase1
from app.services.queue import QueueService
from app.worker.system_user import get_or_create_worker_user

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)


async def process_decisioning_job(payload: dict[str, object]) -> None:
    decision_result_id = UUID(str(payload["decision_result_id"]))
    actor_user_id_raw = payload.get("actor_user_id")
    async with AsyncSessionLocal() as session:
        if actor_user_id_raw:
            actor_user_id = UUID(str(actor_user_id_raw))
        else:
            actor_user_id = (await get_or_create_worker_user(session)).id
        await run_phase1(session, decision_result_id, actor_user_id=actor_user_id)
        await session.commit()


async def main() -> None:
    _log.info("PFL decisioning worker starting")
    settings = get_settings()

    # Build queue service for the decisioning queue specifically
    queue = QueueService(
        region=settings.aws_region,
        endpoint_url=settings.aws_sqs_endpoint_url,
        access_key=settings.aws_access_key_id,
        secret_key=settings.aws_secret_access_key,
        queue_name=settings.sqs_decisioning_queue,
        dlq_name=settings.sqs_decisioning_dlq,
    )
    await queue.ensure_queues_exist()

    while True:
        try:
            await queue.consume_jobs(
                handler=process_decisioning_job,
                wait_seconds=settings.worker_poll_interval_seconds,
            )
        except Exception:
            _log.exception("Decisioning worker loop iteration failed")


if __name__ == "__main__":
    asyncio.run(main())
