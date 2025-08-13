import anyio
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from docent_core._server.util import sse_event_stream
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.server.dependencies.services import get_diff_service
from docent_core.docent.server.dependencies.user import get_default_view_ctx, get_user_anonymous_ok
from docent_core.docent.services.diff import DiffQuery, DiffResult, DiffService

diff_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


class StartDiffRequest(BaseModel):
    query: DiffQuery


@diff_router.post("/{collection_id}/start_diff")
async def start_diff(
    request: StartDiffRequest,
    diff_svc: DiffService = Depends(get_diff_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
):
    query_id = await diff_svc.add_diff_query(ctx, request.query)

    return query_id


@diff_router.get("/{collection_id}/queries")
async def get_all_diff_queries(
    diff_svc: DiffService = Depends(get_diff_service),
    ctx: ViewContext = Depends(get_default_view_ctx),
):
    """Get all diff queries for a collection."""
    queries = await diff_svc.get_all_diff_queries(ctx)
    return queries


@diff_router.get("/{collection_id}/listen_diff")
async def listen_for_diff_results(
    query_id: str,
    diff_svc: DiffService = Depends(get_diff_service),
):
    send_stream, recv_stream = anyio.create_memory_object_stream[list[DiffResult]](
        max_buffer_size=100_000
    )

    async def _execute():
        """Poll for outputs until the query is done."""
        done = False
        while not done:
            results = await diff_svc.get_diff_results(query_id)
            if results is not None:  # type: ignore
                await send_stream.send(results)

            await anyio.sleep(1)

    return StreamingResponse(
        sse_event_stream(_execute, send_stream, recv_stream), media_type="text/event-stream"
    )
