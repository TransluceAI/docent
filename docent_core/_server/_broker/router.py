# import asyncio
# from typing import Optional

# from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

# from docent._log_util import get_logger
# from docent_core._server._broker.redis_client import get_redis_client

# logger = get_logger(__name__)


# broker_router = APIRouter()


# @broker_router.websocket("/{collection_id}")
# async def fg_websocket_endpoint(
#     websocket: WebSocket, collection_id: str, view_id: Optional[str] = Query(None)
# ):
#     """WebSocket endpoint for collection events.

#     Subscribes to:
#     - collection:{collection_id} (always) - for global collection changes
#     - collection:{collection_id}:view:{view_id} (if view_id provided) - for view-specific changes
#     """
#     channels = [f"collection:{collection_id}"]
#     if view_id:
#         channels.append(f"collection:{collection_id}:view:{view_id}")

#     await websocket_loop(websocket, channels)


# @broker_router.websocket("/")
# async def general_websocket_endpoint(websocket: WebSocket):
#     """Used to listen for general events"""
#     await websocket_loop(websocket, ["general:general"])


# async def websocket_loop(websocket: WebSocket, channels: list[str]):
#     await websocket.accept()
#     redis_client = await get_redis_client()
#     pubsub = redis_client.pubsub()  # type: ignore

#     # Subscribe to all requested channels
#     for channel in channels:
#         await pubsub.psubscribe(channel)

#     logger.info(f"WebSocket client subscribed to channels: {channels}")

#     try:
#         while True:
#             message = await pubsub.get_message(timeout=1.0)  # type: ignore
#             if message and message["type"] == "pmessage":
#                 logger.info(f"Websocket sending message from channel {message['channel']}")
#                 await websocket.send_text(message["data"])  # type: ignore
#             await asyncio.sleep(0)  # cooperative
#     except WebSocketDisconnect:
#         logger.info("Client disconnected")
#     finally:
#         # Clean up Redis subscription when client disconnects
#         await pubsub.unsubscribe()  # type: ignore
#         await pubsub.close()
#         logger.info(f"Cleaned up Redis connection for channels: {channels}")
