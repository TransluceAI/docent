import asyncio

from docent._log_util import get_logger
from docent._server._broker.redis_client import REDIS
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = get_logger(__name__)


broker_router = APIRouter()


@broker_router.websocket("/{framegrid_id}")
async def fg_websocket_endpoint(websocket: WebSocket, framegrid_id: str):
    """Used to listen for framegrid-specific events"""
    await websocket_loop(websocket, f"framegrid:{framegrid_id}")


@broker_router.websocket("/")
async def general_websocket_endpoint(websocket: WebSocket):
    """Used to listen for general events"""
    await websocket_loop(websocket, "general:general")


async def websocket_loop(websocket: WebSocket, channel: str):
    await websocket.accept()
    pubsub = REDIS.pubsub()  # type: ignore
    await pubsub.psubscribe(channel)

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
        logger.info(f"Cleaned up Redis connection for {channel}")
