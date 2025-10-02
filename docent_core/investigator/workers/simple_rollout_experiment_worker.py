"""Worker for running simple rollout experiments."""

from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.investigator.db.contexts import WorkspaceContext
from docent_core.investigator.services.monoservice import InvestigatorMonoService
from docent_core.investigator.services.simple_rollout_service import SimpleRolloutService
from docent_core.investigator.tools.simple_rollout import (
    SimpleRolloutExperiment,
    SimpleRolloutExperimentSummary,
)
from docent_core.investigator.workers.experiment_worker_base import run_experiment_job


async def simple_rollout_experiment_job(ctx: WorkspaceContext, job: SQLAJob):
    """Run a simple rollout experiment and stream results to Redis."""
    investigator_svc = await InvestigatorMonoService.init()
    simple_rollout_svc = SimpleRolloutService(investigator_svc)

    await run_experiment_job(
        ctx=ctx,
        job=job,
        service=simple_rollout_svc,
        experiment_factory=SimpleRolloutExperiment,
        summary_type=SimpleRolloutExperimentSummary,
        job_name="simple_rollout",
    )
