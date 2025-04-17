import asyncio
import os
import traceback
from time import perf_counter
from typing import Any, Awaitable, Callable, TypeVar

import sentry_sdk
from docent.loader import EVALS
from docent.server.task_manager import TaskManager
from docent.server.ws_handlers.assistant import (
    handle_create_ta_session,
    handle_diff_transcripts,
    handle_summarize_transcript,
    handle_ta_message,
    rewrite_search_query,
)
from docent.server.ws_handlers.edit_framegrid import (
    handle_add_dimension,
    handle_cluster_dimension,
    handle_cluster_response,
    handle_compute_attributes,
    handle_delete_bin,
    handle_delete_dimension,
    handle_edit_bin,
    handle_recluster_dimension,
    handle_update_base_filter,
)
from docent.server.ws_handlers.forest import (
    handle_get_merged_experiment_tree,
    handle_get_transcript_derivation_tree,
)
from docent.server.ws_handlers.interventions import handle_conversation_intervention
from docent.server.ws_handlers.send_framegrid import (
    compute_and_send_all_marginals,
    handle_get_state,
    handle_marginalize,
    send_datapoint,
    send_datapoint_metadata,
    send_datapoints_updated,
    send_dimensions,
)
from docent.server.ws_handlers.session import (
    handle_create_session,
    handle_get_api_keys,
    handle_join_session,
    handle_set_api_keys,
)
from docent.server.ws_handlers.util import ConnectionManager, WSMessage
from env_util import ENV
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from frames.frame import FrameGrid
from llm_util.types import RateLimitException
from log_util import get_logger
from pydantic import BaseModel
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware  # type: ignore

logger = get_logger(__name__)

asgi_app = FastAPI()
asgi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# If running in production, add Sentry middleware
if ENV.ENV_TYPE == "prod" or os.environ.get("ENABLE_SENTRY", False):
    logger.info("Initializing Sentry for production")
    sentry_sdk.init(  # type: ignore
        dsn="https://c5f049f4a74b7cd17fbf688db7f4838a@o4509013218689024.ingest.us.sentry.io/4509013219803136",
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
    )
    asgi_app.add_middleware(SentryAsgiMiddleware)  # type: ignore


@asgi_app.get("/")
async def root():
    return "clarity has been achieved"


@asgi_app.get("/eval_ids")
async def get_eval_ids():
    return list(EVALS.keys())


class SearchQueryRequest(BaseModel):
    query: str


class SearchQueryResponse(BaseModel):
    rewritten_query: str


@asgi_app.post("/rewrite_search_query", response_model=SearchQueryResponse)
async def api_rewrite_search_query(request: SearchQueryRequest) -> SearchQueryResponse:
    """Endpoint to rewrite a search query to be more detailed and specific.

    Args:
        request: The request containing the search query to rewrite

    Returns:
        SearchQueryResponse: The response containing the rewritten query
    """
    rewritten_query = await rewrite_search_query(request.query)
    return SearchQueryResponse(rewritten_query=rewritten_query)


# These are all local variables! So we don't have to remote them for Modal.
FRAMEGRID_SESSIONS: dict[str, FrameGrid] = {}
CM = ConnectionManager()
TM = TaskManager()
T = TypeVar("T")


def dispatch_task(
    handler: Callable[..., Awaitable[T | None]],
    *args: Any,
    _task_id: str | None = None,
    **kwargs: Any,
) -> asyncio.Task[T | None]:
    """Dispatch a handler as a background task.

    Args:
        handler: The async handler function to run
        *args: Positional arguments to pass to the handler
        **kwargs: Keyword arguments to pass to the handler

    Returns:
        asyncio.Task[T | None]: The created task
    """

    if _task_id:
        logger.info(f"Registering handler {handler.__name__} with pre-specified task_id {_task_id}")

    async def run_handler() -> T | None:
        start_time = perf_counter()
        try:
            result = await handler(*args, **kwargs)
            execution_time = perf_counter() - start_time
            if execution_time < 1.0:
                logger.info(f"{handler.__name__} completed in {execution_time * 1000:.0f}ms")
            else:
                logger.info(f"{handler.__name__} completed in {execution_time:.3f}s")
            return result
        except asyncio.CancelledError:
            execution_time = perf_counter() - start_time
            if execution_time < 1.0:
                logger.info(f"{handler.__name__} cancelled after {execution_time * 1000:.0f}ms")
            else:
                logger.info(f"{handler.__name__} cancelled after {execution_time:.3f}s")
        except Exception as e:
            execution_time = perf_counter() - start_time
            if execution_time < 1.0:
                logger.exception(
                    f"Error in {handler.__name__} after {execution_time * 1000:.0f}ms: {e}. Traceback: {traceback.format_exc()}"
                )
            else:
                logger.exception(
                    f"Error in {handler.__name__} after {execution_time:.3f}s: {e}. Traceback: {traceback.format_exc()}"
                )

            # If we have a websocket, send an error message (most calls are of this form)
            if (
                len(args) >= 2
                and isinstance(args[0], ConnectionManager)
                and isinstance(args[1], WebSocket)
            ):
                cm, ws = args[0], args[1]

                if isinstance(e, RateLimitException):
                    await cm.send(
                        ws,
                        WSMessage(
                            action="rate_limit_error",
                            payload={"message": "enter ur own api key pls"},
                        ),
                    )
                else:
                    await cm.send(
                        ws,
                        WSMessage(
                            action="error", payload={"message": f"Internal server error: {e}"}
                        ),
                    )

    task = asyncio.create_task(run_handler())
    TM.register_task(task, _task_id)
    return task


async def get_fg(fg_id: str | None) -> FrameGrid:
    """Gets a FrameGrid session by ID.

    Args:
        fg_id: The ID of the FrameGrid session to retrieve

    Returns:
        FrameGrid: The requested FrameGrid session

    Raises:
        ValueError: If the session ID is not found
    """
    if fg_id not in FRAMEGRID_SESSIONS:
        raise ValueError(f"Session {fg_id} not found")

    return FRAMEGRID_SESSIONS[fg_id]


async def handle_get_transcript_metadata_fields(
    cm: ConnectionManager, websocket: WebSocket, fg: FrameGrid
):
    first_data = fg.all_data[0] if fg.all_data else None
    if first_data:
        score_types = [
            {
                "name": f"score.{k}",
                "type": type(v).__name__,
            }
            for k, v in first_data.metadata.scores.items()
        ]
    else:
        score_types = []

    await cm.send(
        websocket,
        WSMessage(
            action="transcript_metadata_fields",
            payload={
                "fields": [
                    {
                        "name": "task_id",
                        "type": "str",
                    },
                    {
                        "name": "sample_id",
                        "type": "str | int",
                    },
                    {
                        "name": "epoch_id",
                        "type": "int",
                    },
                    {
                        "name": "experiment_id",
                        "type": "str",
                    },
                    {
                        "name": "model",
                        "type": "str",
                    },
                ]
                + score_types,
            },
        ),
    )


async def handle_cancel_task(cm: ConnectionManager, websocket: WebSocket, msg: WSMessage):
    """Handle cancel_task action by cancelling a running task."""
    task_id = msg.payload["_task_id"]
    success = TM.cancel_task(task_id)

    await cm.send(
        websocket,
        WSMessage(
            action="task_cancel_result",
            payload={
                "task_id": task_id,
                "success": success,
            },
        ),
    )


@asgi_app.websocket("/ws/framegrid")
async def websocket_framegrid_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for FrameGrid sessions."""
    await websocket.accept()
    socket_fg_id: str | None = None
    tasks: list[asyncio.Task[Any]] = []

    try:
        while True:
            raw_data = await websocket.receive_text()
            msg = WSMessage.model_validate_json(raw_data)
            logger.info(f"Got message: {msg}, socket id {socket_fg_id}")

            # Session management
            if msg.action == "create_session":
                ts = perf_counter()
                socket_fg_id = await dispatch_task(
                    handle_create_session, FRAMEGRID_SESSIONS, CM, websocket, msg
                )
                logger.info(f"Time taken to create session: {perf_counter() - ts:.2f}s")
            elif msg.action == "join_session":
                socket_fg_id = await dispatch_task(
                    handle_join_session, FRAMEGRID_SESSIONS, CM, websocket, msg
                )
            elif msg.action == "set_api_keys" and socket_fg_id:
                await dispatch_task(handle_set_api_keys, CM, websocket, socket_fg_id, msg)
                fg = await get_fg(socket_fg_id)
                fg.propagate_api_keys(CM.get_api_keys(socket_fg_id))
            elif msg.action == "get_api_keys" and socket_fg_id:
                await handle_get_api_keys(CM, websocket, socket_fg_id)
            # Task cancellation
            elif msg.action == "cancel_task":
                await handle_cancel_task(CM, websocket, msg)

            # Get transcript metadata fields
            elif msg.action == "get_transcript_metadata_fields":
                fg = await get_fg(socket_fg_id)
                await handle_get_transcript_metadata_fields(CM, websocket, fg)

            # Actions related to updating dimensions
            elif msg.action == "add_dimension":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(handle_add_dimension, CM, websocket, fg, msg, socket_fg_id)
                )
            elif msg.action == "cluster_dimension":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(
                        handle_cluster_dimension,
                        CM,
                        websocket,
                        fg,
                        msg,
                        socket_fg_id,
                        _task_id=msg.payload.get("_task_id"),
                    )
                )
            elif msg.action == "cluster_response":
                tasks.append(dispatch_task(handle_cluster_response, CM, websocket, msg))
            elif msg.action == "compute_attributes":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(
                        handle_compute_attributes,
                        CM,
                        websocket,
                        fg,
                        msg,
                        socket_fg_id,
                        _task_id=msg.payload.get("_task_id"),
                    )
                )
            elif msg.action == "edit_bin":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_edit_bin, CM, websocket, fg, msg))
            elif msg.action == "delete_dimension":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_delete_dimension, CM, websocket, fg, msg))
            elif msg.action == "delete_bin":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_delete_bin, CM, websocket, fg, msg))
            elif msg.action == "update_base_filter":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_update_base_filter, CM, websocket, fg, msg))
            elif msg.action == "recluster_dimension":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(
                        handle_recluster_dimension,
                        CM,
                        websocket,
                        fg,
                        msg,
                        socket_fg_id,
                        _task_id=msg.payload.get("_task_id"),
                    )
                )

            # Interventions
            elif msg.action == "conversation_intervention":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(
                        handle_conversation_intervention, CM, websocket, fg, msg, socket_fg_id
                    )
                )

            # Actions related to getting state
            elif msg.action == "get_state":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_get_state, CM, websocket, fg))
            elif msg.action == "get_dimensions":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(send_dimensions, CM, websocket, fg))
            elif msg.action == "get_marginals":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(compute_and_send_all_marginals, CM, websocket, fg))
            elif msg.action == "get_transcripts":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(send_datapoints_updated, CM, websocket))
            elif msg.action == "marginalize":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_marginalize, CM, websocket, fg, msg))
            elif msg.action == "get_datapoint":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(send_datapoint, CM, websocket, fg, msg, is_diff=False))
            elif msg.action == "get_diff_datapoint":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(send_datapoint, CM, websocket, fg, msg, is_diff=True))
            elif msg.action == "get_datapoint_metadata":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(send_datapoint_metadata, CM, websocket, fg, msg))

            # Actions related to transcript assistant
            elif msg.action == "create_ta_session":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_create_ta_session, CM, websocket, fg, msg))
            elif msg.action == "ta_message":
                fg = await get_fg(socket_fg_id)
                tasks.append(dispatch_task(handle_ta_message, CM, websocket, fg, msg, socket_fg_id))
            elif msg.action == "summarize_transcript":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(
                        handle_summarize_transcript,
                        CM,
                        websocket,
                        fg,
                        msg,
                        _task_id=msg.payload.get("_task_id"),
                        socket_fg_id=socket_fg_id,
                    )
                )
            elif msg.action == "diff_transcripts":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(
                        handle_diff_transcripts,
                        CM,
                        websocket,
                        fg,
                        msg,
                        _task_id=msg.payload.get("_task_id"),
                        socket_fg_id=socket_fg_id,
                    )
                )

            # Actions related to forest visualization
            elif msg.action == "get_merged_experiment_tree":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(handle_get_merged_experiment_tree, CM, websocket, fg, msg)
                )
            elif msg.action == "get_transcript_derivation_tree":
                fg = await get_fg(socket_fg_id)
                tasks.append(
                    dispatch_task(handle_get_transcript_derivation_tree, CM, websocket, fg, msg)
                )

            # Unknown action
            else:
                raise ValueError("Unknown action")

    except WebSocketDisconnect:
        # Cancel all active tasks
        for task in tasks:
            if not task.done():
                task.cancel()

        # Clean up resources
        if socket_fg_id is not None:
            CM.disconnect(socket_fg_id, websocket)

        logger.info(f"Websocket {socket_fg_id} disconnected")

    except Exception as e:
        logger.exception(f"Error in websocket loop: {e}. Traceback: {traceback.format_exc()}")
