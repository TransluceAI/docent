import json
from typing import Any

import redis.asyncio as redis
from fastapi.encoders import jsonable_encoder

REDIS = redis.from_url("redis://localhost:6379", decode_responses=True)  # type: ignore


async def publish_to_broker(framegrid_id: str, data: dict[str, Any]):
    """Publish a message to the broker for a specific framegrid.

    Args:
        framegrid_id: The ID of the framegrid to publish to
        data: The data to publish (will be converted to JSON)
    """
    channel = f"framegrid:{framegrid_id}"
    await REDIS.publish(channel, json.dumps(jsonable_encoder(data)))  # type: ignore
