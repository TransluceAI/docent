import json
from typing import Any

import anyio
import redis.asyncio as redis
from arq import ArqRedis
from fastapi.encoders import jsonable_encoder

from docent._log_util import get_logger
from docent_core._env_util import ENV
from docent_core._worker.constants import WORKER_QUEUE_NAME
from docent_core.docent.db.contexts import ViewContext
from docent_core.investigator.db.contexts import WorkspaceContext

logger = get_logger(__name__)


_redis_client: ArqRedis | None = None
_redis_lock = anyio.Lock()

STREAM_KEY_FORMAT = "stream_{job_id}"
STATE_KEY_FORMAT = "state_{job_id}"
SUBSCRIPTIONS_KEY_FORMAT = "agent_run:subscriptions:{job_id}"


def get_redis_url() -> str:
    host = ENV.get("DOCENT_REDIS_HOST")
    port = ENV.get("DOCENT_REDIS_PORT")

    if not host or not port:
        raise ValueError("DOCENT_REDIS_HOST, DOCENT_REDIS_PORT must be set")

    user = ENV.get("DOCENT_REDIS_USER")
    password = ENV.get("DOCENT_REDIS_PASSWORD")
    tls = (ENV.get("DOCENT_REDIS_TLS", "false") or "false").strip().lower() == "true"

    protocol = "rediss" if tls else "redis"
    auth = ""
    if user and password:
        auth = f"{user}:{password}@"
    elif user:
        auth = f"{user}@"
    elif password:
        auth = f":{password}@"

    return f"{protocol}://{auth}{host}:{port}"


async def get_redis_client():
    global _redis_client

    async with _redis_lock:
        if _redis_client is None:
            url = get_redis_url()
            _redis_client = ArqRedis(connection_pool=redis.ConnectionPool.from_url(url, decode_responses=True))  # type: ignore

            logger.info(f"Checking Redis connection to {url}")
            await verify_redis_connection(_redis_client)

        return _redis_client


async def verify_redis_connection(redis_client: ArqRedis) -> None:
    """
    Verify that the Redis connection is working by attempting to ping the server.

    Args:
        redis_client: The Redis client to test

    Raises:
        ConnectionError: If unable to connect to Redis
    """
    try:
        result = await redis_client.ping()  # type: ignore
        if result:
            logger.info("Successfully pinged Redis")
        else:
            raise ConnectionError("Redis ping returned False")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise ConnectionError(f"Unable to connect to Redis: {e}") from e


async def publish_to_broker(collection_id: str | None, data: dict[str, Any]):
    """Publish a message to the broker for a specific collection.

    Args:
        collection_id: The ID of the collection to publish to
        data: The data to publish (will be converted to JSON)
    """
    redis_client = await get_redis_client()

    channel = f"collection:{collection_id}" if collection_id is not None else "general:general"
    print(f"Publishing to channel {channel}!!!!!!")
    await redis_client.publish(channel, json.dumps(jsonable_encoder(data)))  # type: ignore
    print(f"Published to channel {channel}!!!!!!")


async def publish_collection_update(collection_id: str, payload: dict[str, Any]):
    """Publish a collection-wide update that all clients viewing this collection should receive.

    Use this for global changes like:
    - Adding/removing agent runs
    - Modifying collection metadata
    - Updating dimensions
    - Global filter changes

    Args:
        collection_id: The collection ID
        payload: The data to publish (will be converted to JSON)
    """
    redis_client = await get_redis_client()
    channel = f"collection:{collection_id}"
    await redis_client.publish(channel, json.dumps(jsonable_encoder(payload)))  # type: ignore


async def publish_view_update(collection_id: str, view_id: str, payload: dict[str, Any]):
    """Publish a view-specific update that only clients viewing this specific view should receive.

    Use this for view-local changes like:
    - View-specific filter updates
    - View title/description changes
    - View-scoped UI state

    Args:
        collection_id: The collection ID
        view_id: The view ID
        payload: The data to publish (will be converted to JSON)
    """
    redis_client = await get_redis_client()
    channel = f"collection:{collection_id}:view:{view_id}"
    await redis_client.publish(channel, json.dumps(jsonable_encoder(payload)))  # type: ignore


async def _enqueue_job(queue_name: str, func_name: str, *args: Any, **kwargs: Any) -> None:
    redis_client = await get_redis_client()
    j = await redis_client.enqueue_job(func_name, *args, _queue_name=queue_name, **kwargs)
    print(f"Enqueued job {j} to {queue_name} with func {func_name}")


async def enqueue_job(ctx: ViewContext | WorkspaceContext, job_id: str) -> None:
    """Enqueue a job to the worker."""
    await _enqueue_job(WORKER_QUEUE_NAME, "run_job", ctx, job_id)


async def cancel_job(job_id: str) -> None:
    """Cancel a job and wait for confirmation that the cancellation was processed."""
    redis_client = await get_redis_client()
    # Queue names
    command_queue = f"commands_{job_id}"
    response_queue = f"cancel_response_{job_id}"

    # Send the cancel command with the response ID
    await redis_client.rpush(command_queue, "cancel")  # type: ignore

    # Wait for confirmation from the worker
    try:
        # Wait up to T seconds for cancellation confirmation
        result = await redis_client.blpop(response_queue, timeout=10)  # type: ignore
        if result is None:
            raise TimeoutError(f"Timeout waiting for cancellation confirmation for job {job_id}")

        _queue_name, response = result  # type: ignore
        logger.info(f"Received cancellation confirmation for job {job_id}: {response}")

    except Exception as e:
        logger.error(f"Error waiting for cancellation confirmation for job {job_id}: {e}")

    finally:
        await redis_client.delete(response_queue)  # type: ignore
