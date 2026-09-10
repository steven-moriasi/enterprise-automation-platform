import signal
import socket
import uuid
from threading import Event

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.database import SessionFactory
from app.infrastructure.queue import RedisExecutionQueue
from app.services.executions import ExecutionService

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
    worker_id = f"{socket.gethostname()}:{uuid.uuid4()}"
    logger.info("worker_started", worker_id=worker_id)
    while not shutdown.is_set():
        execution_id = queue.dequeue(timeout_seconds=max(1, round(settings.worker_poll_seconds)))
        if execution_id is None:
            continue
        with SessionFactory() as session:
            processed = ExecutionService(
                session,
                worker_id=worker_id,
                lease_seconds=settings.worker_lease_seconds,
            ).run(execution_id)
            logger.info(
                "execution_delivery_handled",
                execution_id=execution_id,
                claimed=processed,
            )
    logger.info("worker_stopped")


if __name__ == "__main__":
    run()
