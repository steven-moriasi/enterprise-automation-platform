from functools import lru_cache

from app.core.config import get_settings
from app.infrastructure.queue import RedisExecutionQueue


@lru_cache
def get_execution_queue() -> RedisExecutionQueue:
    return RedisExecutionQueue(get_settings().redis_url)
