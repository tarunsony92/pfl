"""backend/app/worker/__main__.py — entrypoint: `python -m app.worker`"""

import asyncio
import logging

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.services.queue import get_queue
from app.worker.pipeline import process_ingestion_job, set_system_worker_user_id
from app.worker.system_user import get_or_create_worker_user

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)


async def main() -> None:
    _log.info("PFL ingestion worker starting")
    async with AsyncSessionLocal() as session:
        user = await get_or_create_worker_user(session)
        await session.commit()
    set_system_worker_user_id(user.id)
    _log.info("System worker user: %s", user.id)

    queue = get_queue()
    settings = get_settings()

    while True:
        try:
            await queue.consume_jobs(
                handler=process_ingestion_job,
                wait_seconds=settings.worker_poll_interval_seconds,
            )
        except Exception:
            _log.exception("Worker loop iteration failed")


if __name__ == "__main__":
    asyncio.run(main())
