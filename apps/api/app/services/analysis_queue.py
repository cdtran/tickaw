"""Redis Stream transport for durable database-backed analysis runs."""

import logging
from functools import lru_cache
from uuid import UUID

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)
STREAM = "tickaw:analysis:runs"
GROUP = "analysis-workers"


@lru_cache
def get_queue() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=7,
    )


def enqueue_run(run_id: UUID) -> bool:
    """Publish a committed run; the database recovery scan covers broker outages."""
    try:
        get_queue().xadd(STREAM, {"run_id": str(run_id)})
    except redis.RedisError:
        logger.exception("Could not enqueue analysis run=%s; database recovery will retry", run_id)
        return False
    return True
