from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.db import DocentDB
from docent_core._db_service.schemas.tables import SQLAJob
from docent_core._db_service.service import MonoService
from docent_core.services.rubric import RubricService


async def rubric_job(ctx: ViewContext, job: SQLAJob):
    db = await DocentDB.init()
    mono_svc = await MonoService.init()

    # Communicate the total number of agent runs
    # TODO(mengk): slightly hacky, not sure what's better tho
    await mono_svc.set_job_json(
        job.id, job.job_json | {"total_agent_runs": await mono_svc.count_base_agent_runs(ctx)}
    )

    async with db.session() as session:
        rs = RubricService(session, db.session, mono_svc)
        await rs.run_rubric_job(ctx, job)
