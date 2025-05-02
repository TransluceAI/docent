import asyncio

from docent._server._broker.redis_client import REDIS
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from log_util import get_logger

logger = get_logger(__name__)


broker_router = APIRouter()


@broker_router.websocket("/{framegrid_id}")
async def websocket_endpoint(websocket: WebSocket, framegrid_id: str):
    await websocket.accept()
    pubsub = REDIS.pubsub()
    await pubsub.psubscribe(f"framegrid:{framegrid_id}")

    try:
        while True:
            message = await pubsub.get_message(timeout=1.0)
            if message and message["type"] == "pmessage":
                logger.info("Websocket sending message")
                await websocket.send_text(message["data"])
            await asyncio.sleep(0)  # cooperative
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    finally:
        # Clean up Redis subscription when client disconnects
        await pubsub.unsubscribe()
        await pubsub.close()
        logger.info(f"Cleaned up Redis connection for {framegrid_id}")


# # Keep the original SSE endpoint for backward compatibility
# @rest_router.get("/sse/{framegrid_id}")
# async def stream(framegrid_id: str, request: Request):
#     pubsub = r.pubsub()
#     await pubsub.psubscribe(f"framegrid:{framegrid_id}")

#     async def event_generator():
#         try:
#             while True:
#                 if await request.is_disconnected():
#                     logger.info("Client disconnected")
#                     break
#                 message = await pubsub.get_message(timeout=1.0)
#                 logger.info("Listener got message")
#                 if message and message["type"] == "pmessage":
#                     yield f"data: {message['data']}\n\n"
#                 await asyncio.sleep(0)  # cooperative
#         finally:
#             # Clean up Redis subscription when client disconnects
#             await pubsub.unsubscribe()
#             await pubsub.close()
#             logger.info(f"Cleaned up Redis connection for {framegrid_id}")

#     headers = {
#         "Cache-Control": "no-cache",
#         "Content-Type": "text/event-stream",
#         "X-Accel-Buffering": "no",
#     }
#     return StreamingResponse(event_generator(), headers=headers)
