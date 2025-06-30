import json
from typing import Any

import redis.asyncio as redis
from arq import ArqRedis
from fastapi.encoders import jsonable_encoder

from docent_core._db_service.contexts import ViewContext
from docent_core._env_util import ENV


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


async def enqueue_search_job(view_ctx: ViewContext, job_id: str, read_only: bool) -> None:
    await _enqueue_job("embedding_and_search_queue", "compute_search", view_ctx, job_id, read_only)


async def enqueue_embedding_job(view_ctx: ViewContext, job_id: str) -> None:
    """Enqueue an embedding computation job to the worker."""
    await _enqueue_job("embedding_and_search_queue", "compute_embeddings", view_ctx, job_id)
