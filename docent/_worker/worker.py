import asyncio
import json
from typing import Any

import anyio
import redis.asyncio as redis
from arq import ArqRedis
from arq.connections import RedisSettings
from arq.worker import run_worker
from pydantic_core import to_jsonable_python

from docent._ai_tools.search import SearchResult
from docent._db_service.contexts import ViewContext
from docent._db_service.schemas.tables import JobStatus
from docent._db_service.service import DBService
from docent._env_util import ENV
from docent._server._rest.send_state import publish_searches

REDIS_HOST = ENV.get("DOCENT_REDIS_HOST")
REDIS_PORT = ENV.get("DOCENT_REDIS_PORT")


REDIS = ArqRedis(
    connection_pool=redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
)


async def compute_search(ctx: dict[Any, Any], view_ctx: ViewContext, job_id: str):
    print("compute search:", view_ctx, job_id)

    db = await DBService.init()
    result = await db.get_search_job_and_query(job_id)
    if result is None:
        print(f"Search job {job_id} not found")
        return
    _job, query = result

    await db.set_job_status(job_id, JobStatus.RUNNING)

    async def _search_result_callback(search_results: list[SearchResult] | None) -> None:
        if search_results or search_results is None:
            await REDIS.xadd(
                f"results_{job_id}", {"results": json.dumps(to_jsonable_python(search_results))}
            )
            with anyio.CancelScope(shield=True):
                await publish_searches(db, view_ctx)

    canceled = False

    async def run():
        nonlocal canceled
        try:
            async with db.advisory_lock(view_ctx.fg_id, action_id="mutation"):
                await db.compute_search(view_ctx, query.search_query, _search_result_callback)
        except:
            canceled = True
            raise
        finally:
            with anyio.CancelScope(shield=True):
                if canceled:
                    print(f"job {job_id} canceled")
                    await db.set_job_status(job_id, JobStatus.CANCELED)
                else:
                    print(f"job {job_id} completed")
                    await db.set_job_status(job_id, JobStatus.COMPLETED)

                await publish_searches(db, view_ctx)
                await REDIS.delete(f"results_{job_id}")

    async def await_commands():
        q = f"commands_{job_id}"

        while True:
            _queue, command = await REDIS.blpop(q)
            print(f"{job_id} received {command}")
            match command:
                case "cancel":
                    # The search task may internally prevent cancellation requests from bubbling all
                    # the way up, so explicitly note down the cancellation if we do it ourselves.
                    nonlocal canceled
                    canceled = True

                    run_task.cancel()

    run_task = asyncio.create_task(run())
    commands_task = asyncio.create_task(await_commands())

    _, pending = await asyncio.wait([run_task, commands_task], return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()

    print(f"worker finishing job {job_id}")


def run():
    run_worker(
        {
            "functions": [compute_search],
            "redis_settings": RedisSettings(host=REDIS_HOST, port=REDIS_PORT),
            "queue_name": "compute_search_queue",
            "max_jobs": 5,  # Allow up to 5 concurrent jobs per worker
        }
    )
