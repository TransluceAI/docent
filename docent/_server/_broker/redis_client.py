import json
from typing import Any

import redis.asyncio as redis
from arq import ArqRedis
from fastapi.encoders import jsonable_encoder

from docent._db_service.contexts import ViewContext
from docent._env_util import ENV


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


async def publish_to_broker(framegrid_id: str | None, data: dict[str, Any]):
    """Publish a message to the broker for a specific framegrid.

    Args:
        framegrid_id: The ID of the framegrid to publish to
        data: The data to publish (will be converted to JSON)
    """
    channel = f"framegrid:{framegrid_id}" if framegrid_id is not None else "general:general"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(data)))  # type: ignore


async def publish_framegrid_update(fg_id: str, payload: dict[str, Any]):
    """Publish a framegrid-wide update that all clients viewing this framegrid should receive.

    Use this for global changes like:
    - Adding/removing agent runs
    - Modifying framegrid metadata
    - Updating dimensions
    - Global filter changes

    Args:
        fg_id: The framegrid ID
        payload: The data to publish (will be converted to JSON)
    """
    channel = f"framegrid:{fg_id}"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(payload)))  # type: ignore


async def publish_view_update(fg_id: str, view_id: str, payload: dict[str, Any]):
    """Publish a view-specific update that only clients viewing this specific view should receive.

    Use this for view-local changes like:
    - View-specific filter updates
    - View title/description changes
    - View-scoped UI state

    Args:
        fg_id: The framegrid ID
        view_id: The view ID
        payload: The data to publish (will be converted to JSON)
    """
    channel = f"framegrid:{fg_id}:view:{view_id}"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(payload)))  # type: ignore


async def _enqueue_job(queue_name: str, func_name: str, *args: Any, **kwargs: Any):
    j = await REDIS.enqueue_job(func_name, *args, _queue_name=queue_name, **kwargs)
    print("enqueued", queue_name, func_name, args, kwargs, j)


async def enqueue_search_job(view_ctx: ViewContext, job_id: str):
    await _enqueue_job("compute_search_queue", "compute_search", view_ctx, job_id)
