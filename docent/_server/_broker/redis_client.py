import json
from typing import Any

import redis.asyncio as redis
from docent._env_util import ENV
from fastapi.encoders import jsonable_encoder

REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")
if REDIS_HOST is None or REDIS_PORT is None:
    raise ValueError("DOCENT_REDIS_HOST and DOCENT_REDIS_PORT must be set")

REDIS = redis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}", decode_responses=True)  # type: ignore


async def publish_to_broker(framegrid_id: str, data: dict[str, Any]):
    """Publish a message to the broker for a specific framegrid.

    Args:
        framegrid_id: The ID of the framegrid to publish to
        data: The data to publish (will be converted to JSON)
    """
    channel = f"framegrid:{framegrid_id}"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(data)))  # type: ignore
