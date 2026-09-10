import signal
from threading import Event

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.database import SessionFactory
from app.infrastructure.queue import RedisExecutionQueue
from app.services.scheduling import (
    prepare_due_retries,
    prepare_due_schedules,
    publish_dispatch_outbox,
)

shutdown = Event()
logger = structlog.get_logger()


def request_shutdown(_signum: int, _frame: object) -> None:
    shutdown.set()


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    queue = RedisExecutionQueue(settings.redis_url)
    logger.info("scheduler_started")
    while not shutdown.is_set():
        with SessionFactory() as session:
            schedules = prepare_due_schedules(session)
            retries = prepare_due_retries(session)
            published = publish_dispatch_outbox(session, queue)
            if schedules or retries or published:
                logger.info(
                    "scheduler_cycle_completed",
                    schedules_prepared=schedules,
                    retries_prepared=retries,
                    dispatches_published=published,
                )
        shutdown.wait(settings.scheduler_poll_seconds)
    logger.info("scheduler_stopped")


if __name__ == "__main__":
    run()
