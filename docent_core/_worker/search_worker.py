import json

import anyio
from arq import ArqRedis
from pydantic_core import to_jsonable_python

from docent._log_util import get_logger
from docent_core._ai_tools.search import SearchResult
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.tables import JobStatus
from docent_core._db_service.service import MonoService

logger = get_logger(__name__)


async def compute_search(view_ctx: ViewContext, job_id: str, read_only: bool, REDIS: ArqRedis):
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
            # with anyio.CancelScope(shield=True):
            # await publish_searches(mono_svc, view_ctx)

    async with mono_svc.advisory_lock(
        view_ctx.collection_id + "__search__" + query.id,
        action_id="mutation",
    ):
        await mono_svc.compute_search(
            view_ctx,
            query.id,
            _search_result_callback,
            read_only,
        )
    with anyio.CancelScope(shield=True):

        # await publish_searches(mono_svc, view_ctx)
        await REDIS.delete(f"results_{job_id}")
