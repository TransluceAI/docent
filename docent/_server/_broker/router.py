import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from docent._log_util import get_logger
from docent._server._broker.redis_client import REDIS

logger = get_logger(__name__)


broker_router = APIRouter()


@broker_router.websocket("/{framegrid_id}")
async def websocket_endpoint(websocket: WebSocket, framegrid_id: str):
    await websocket.accept()
    pubsub = REDIS.pubsub()  # type: ignore
    await pubsub.psubscribe(f"framegrid:{framegrid_id}")

    try:
        while True:
            message = await pubsub.get_message(timeout=1.0)  # type: ignore
            if message and message["type"] == "pmessage":
                logger.info("Websocket sending message")
                await websocket.send_text(message["data"])  # type: ignore
            await asyncio.sleep(0)  # cooperative
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    finally:
        # Clean up Redis subscription when client disconnects
        await pubsub.unsubscribe()  # type: ignore
        await pubsub.close()
        logger.info(f"Cleaned up Redis connection for {framegrid_id}")
