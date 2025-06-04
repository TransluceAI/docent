import json

import anyio
import redis.asyncio as redis
from arq import ArqRedis
from arq.connections import RedisSettings
from arq.worker import run_worker
from pydantic_core import to_jsonable_python

from docent._ai_tools.search import SearchResult
from docent._db_service.contexts import ViewContext
from docent._db_service.service import DBService
from docent._env_util import ENV
from docent._server._rest.send_state import publish_searches

REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")


REDIS = ArqRedis(
    connection_pool=redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
)


async def compute_search(ctx: dict, view_ctx: ViewContext, job_id: str):
    print("compute search:", view_ctx, job_id)

    db = await DBService.init()
    job, query = await db.get_search_job_and_query(job_id)

    print("running job for search query:", query)

    async def _search_result_callback(search_results: list[SearchResult]) -> None:
        if search_results:
            await REDIS.xadd(
                f"results_{job_id}", {"results": json.dumps(to_jsonable_python(search_results))}
            )
            with anyio.CancelScope(shield=True):
                await publish_searches(db, view_ctx)

    async with db.advisory_lock(view_ctx.fg_id, action_id="mutation"):
        try:
            await db.compute_search(view_ctx, query.search_query, _search_result_callback)
        finally:
            with anyio.CancelScope(shield=True):
                await publish_searches(db, view_ctx)


def run():
    run_worker(
        {
            "functions": [compute_search],
            "redis_settings": RedisSettings(host=REDIS_HOST, port=REDIS_PORT),
            "queue_name": "compute_search_queue",
        }
    )
