import json
from typing import Awaitable, Callable

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream


async def sse_event_stream(
    execute: Callable[[], Awaitable[None]], recv_stream: MemoryObjectReceiveStream
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

    async with anyio.create_task_group() as tg:
        tg.start_soon(execute)

        async for payload in recv_stream:
            data = json.dumps(payload)
            yield f"data: {data}\n\n"

    yield "data: [DONE]\n\n"
