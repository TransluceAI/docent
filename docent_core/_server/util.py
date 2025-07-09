import json
from typing import Any, Awaitable, Callable

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic_core import to_jsonable_python


async def sse_event_stream(
    execute: Callable[[], Awaitable[None]],
    send_stream: MemoryObjectSendStream[Any],
    recv_stream: MemoryObjectReceiveStream[Any],
):
    """Creates a Server-Sent Events (SSE) stream from an execution function and a receive stream.
    NOTE: This function will never complete if recv_stream is not closed.

    Args:
        execute: A callable that returns an awaitable. This function will be executed
            in a separate task and is responsible for sending data to the receive stream.
        recv_stream: A memory object receive stream that will provide the data to be
            sent as SSE events.

    Yields:
        str: SSE formatted event strings.
    """

    async def _execute_and_close_stream():
        await execute()
        await send_stream.aclose()

    async with anyio.create_task_group() as tg:
        tg.start_soon(_execute_and_close_stream)

        async for payload in recv_stream:
            data = json.dumps(to_jsonable_python(payload))
            yield f"data: {data}\n\n"

    yield "data: [DONE]\n\n"
