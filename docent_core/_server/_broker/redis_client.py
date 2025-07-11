import json
from typing import Any

import redis.asyncio as redis
from arq import ArqRedis
from fastapi.encoders import jsonable_encoder

from docent._log_util import get_logger
from docent_core._db_service.contexts import ViewContext
from docent_core._env_util import ENV
from docent_core._worker.constants import WORKER_QUEUE_NAME

logger = get_logger(__name__)


def _get_redis_client():
    REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
    REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")
    REDIS_USER = ENV.get("DOCENT_REDIS_USER")
    REDIS_PASSWORD = ENV.get("DOCENT_REDIS_PASSWORD")
    if any(v is None for v in [REDIS_HOST, REDIS_PORT, REDIS_USER, REDIS_PASSWORD]):
        raise ValueError(
            "DOCENT_REDIS_HOST, DOCENT_REDIS_PORT, DOCENT_REDIS_USER, and DOCENT_REDIS_PASSWORD must all be set"
        )
    REDIS_USER_STRING = (
        f"{REDIS_USER}:{REDIS_PASSWORD}@"
        if REDIS_USER is not None and REDIS_PASSWORD is not None
        else ""
    )
    url = f"redis://{REDIS_USER_STRING}{REDIS_HOST}:{REDIS_PORT}"
    return ArqRedis(connection_pool=redis.ConnectionPool.from_url(url, decode_responses=True))  # type: ignore


REDIS = _get_redis_client()


async def publish_to_broker(collection_id: str | None, data: dict[str, Any]):
    """Publish a message to the broker for a specific collection.

    Args:
        collection_id: The ID of the collection to publish to
        data: The data to publish (will be converted to JSON)
    """
    channel = f"collection:{collection_id}" if collection_id is not None else "general:general"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(data)))  # type: ignore


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
    channel = f"collection:{collection_id}"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(payload)))  # type: ignore


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
    channel = f"collection:{collection_id}:view:{view_id}"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(payload)))  # type: ignore


async def _enqueue_job(queue_name: str, func_name: str, *args: Any, **kwargs: Any) -> None:
    j = await REDIS.enqueue_job(func_name, *args, _queue_name=queue_name, **kwargs)
    print(f"Enqueued job {j} to {queue_name} with func {func_name}")


async def enqueue_search_job(view_ctx: ViewContext, job_id: str) -> None:
    await _enqueue_job(WORKER_QUEUE_NAME, "run_job", view_ctx, job_id)


async def enqueue_embedding_job(view_ctx: ViewContext, job_id: str) -> None:
    """Enqueue an embedding computation job to the worker."""
    await _enqueue_job(WORKER_QUEUE_NAME, "run_job", view_ctx, job_id)


async def enqueue_rubric_job(view_ctx: ViewContext, job_id: str) -> None:
    """Enqueue an rubric job to the worker."""
    await _enqueue_job(WORKER_QUEUE_NAME, "run_job", view_ctx, job_id)


async def cancel_job(job_id: str) -> None:
    """Cancel a job and wait for confirmation that the cancellation was processed."""
    # Queue names
    command_queue = f"commands_{job_id}"
    response_queue = f"cancel_response_{job_id}"

    # Send the cancel command with the response ID
    await REDIS.rpush(command_queue, "cancel")  # type: ignore

    # Wait for confirmation from the worker
    try:
        # Wait up to T seconds for cancellation confirmation
        result = await REDIS.blpop(response_queue, timeout=10)  # type: ignore
        if result is None:
            raise TimeoutError(f"Timeout waiting for cancellation confirmation for job {job_id}")

        _queue_name, response = result  # type: ignore
        logger.info(f"Received cancellation confirmation for job {job_id}: {response}")

    except Exception as e:
        logger.error(f"Error waiting for cancellation confirmation for job {job_id}: {e}")

    finally:
        await REDIS.delete(response_queue)  # type: ignore
