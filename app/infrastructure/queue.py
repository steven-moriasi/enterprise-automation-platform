from typing import Protocol

from redis import Redis


class ExecutionDispatcher(Protocol):
    def enqueue(self, execution_id: str) -> None: ...


class RedisExecutionQueue:
    queue_name = "automation:executions"

    def __init__(self, redis_url: str) -> None:
        self.client: Redis = Redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, execution_id: str) -> None:
        self.client.rpush(self.queue_name, execution_id)

    def dequeue(self, timeout_seconds: int = 5) -> str | None:
        item = self.client.blpop(self.queue_name, timeout=timeout_seconds)
        return item[1] if item else None

    def ping(self) -> bool:
        return bool(self.client.ping())
