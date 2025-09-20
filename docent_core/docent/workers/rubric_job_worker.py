from docent_core._db_service.db import DocentDB
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService


async def rubric_job(ctx: ViewContext, job: SQLAJob):
    db = await DocentDB.init()
    mono_svc = await MonoService.init()

    async with db.session() as session:
        rs = RubricService(session, db.session, mono_svc)
        await rs.run_rubric_job(ctx, job)
