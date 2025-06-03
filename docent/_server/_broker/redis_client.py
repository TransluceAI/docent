import json
from typing import Any

import redis.asyncio as redis
from fastapi.encoders import jsonable_encoder

from docent._env_util import ENV

REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")
if REDIS_HOST is None or REDIS_PORT is None:
    raise ValueError("DOCENT_REDIS_HOST and DOCENT_REDIS_PORT must be set")

REDIS = redis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}", decode_responses=True)  # type: ignore


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
