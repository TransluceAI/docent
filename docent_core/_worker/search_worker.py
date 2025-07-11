import json
from typing import Any

import anyio
from anyio.abc import TaskGroup
from arq import ArqRedis
from pydantic_core import to_jsonable_python

from docent._log_util import get_logger
from docent_core._ai_tools.search import SearchResult
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.tables import JobStatus
from docent_core._db_service.service import MonoService
from docent_core._server._rest.send_state import publish_searches

logger = get_logger(__name__)


async def compute_search(
    _: dict[Any, Any], view_ctx: ViewContext, job_id: str, read_only: bool, REDIS: ArqRedis
):
    """
    TODO(mengk): get rid of the REDIS dependency
    """
    mono_svc = await MonoService.init()
    result = await mono_svc.get_search_job_and_query(job_id)
    if result is None:
        logger.error(f"Search job {job_id} not found")
        return
    _job, query = result

    await mono_svc.set_job_status(job_id, JobStatus.RUNNING)

    async def _search_result_callback(
        search_results: list[SearchResult] | None,
    ) -> None:
        if search_results or search_results is None:
            await REDIS.xadd(
                f"results_{job_id}",
                {"results": json.dumps(to_jsonable_python(search_results))},
            )
            with anyio.CancelScope(shield=True):
                await publish_searches(mono_svc, view_ctx)

    canceled = False

    async def run(tg: TaskGroup):
        nonlocal canceled
        try:
            async with mono_svc.advisory_lock(
                view_ctx.collection_id + "__search__" + query.search_query,
                action_id="mutation",
            ):
                await mono_svc.compute_search(
                    view_ctx,
                    query.search_query,
                    _search_result_callback,
                    read_only,
                )
                tg.cancel_scope.cancel()
        except:
            canceled = True
            raise
        finally:
            with anyio.CancelScope(shield=True):
                if canceled:
                    logger.highlight(f"Job {job_id} canceled", color="red")
                    await mono_svc.set_job_status(job_id, JobStatus.CANCELED)
                else:
                    logger.highlight(f"Job {job_id} finished", color="green")
                    await mono_svc.set_job_status(job_id, JobStatus.COMPLETED)

                await publish_searches(mono_svc, view_ctx)
                await REDIS.delete(f"results_{job_id}")

    async def await_commands(tg: TaskGroup):
        nonlocal canceled
        q = f"commands_{job_id}"

        while True:
            _queue, command = await REDIS.blpop(q)  # type: ignore
            logger.info(f"{job_id} received {command}")

            match command:  # type: ignore
                case "cancel":
                    # The search task may internally prevent cancellation requests from bubbling all
                    # the way up, so explicitly note down the cancellation if we do it ourselves.
                    canceled = True

                    tg.cancel_scope.cancel()

    async with anyio.create_task_group() as tg:
        tg.start_soon(run, tg)
        tg.start_soon(await_commands, tg)
