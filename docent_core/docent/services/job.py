from typing import AsyncContextManager, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core._server._broker.redis_client import cancel_job
from docent_core.docent.db.schemas.tables import JobStatus, SQLAJob

logger = get_logger(__name__)


class JobService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    ):
        self.session = session
        self.session_cm_factory = session_cm_factory

    async def get_job(self, job_id: str) -> SQLAJob | None:
        result = await self.session.execute(select(SQLAJob).where(SQLAJob.id == job_id))
        return result.scalar_one_or_none()

    async def cancel_job(self, job_id: str):
        job = await self.get_job(job_id)
        if job is None:
            logger.warning(f"No job to cancel: {job_id}")
            return

        # Only cancel the job if it's still active
        if job.status in [JobStatus.PENDING, JobStatus.RUNNING]:
            await cancel_job(job_id)
        else:
            logger.warning(f"Job {job_id} is not active: {job.status}")
