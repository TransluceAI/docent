"""Worker for running counterfactual experiments."""

from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.investigator.db.contexts import WorkspaceContext
from docent_core.investigator.services.counterfactual_service import CounterfactualService
from docent_core.investigator.services.monoservice import InvestigatorMonoService
from docent_core.investigator.tools.counterfactual_analysis.counterfactual_experiment import (
    CounterfactualExperiment,
)
from docent_core.investigator.tools.counterfactual_analysis.types import (
    CounterfactualExperimentSummary,
)
from docent_core.investigator.workers.experiment_worker_base import run_experiment_job


async def counterfactual_experiment_job(ctx: WorkspaceContext, job: SQLAJob):
    """Run a counterfactual experiment and stream results to Redis."""
    investigator_svc = await InvestigatorMonoService.init()
    counterfactual_svc = CounterfactualService(investigator_svc)

    await run_experiment_job(
        ctx=ctx,
        job=job,
        service=counterfactual_svc,
        experiment_factory=CounterfactualExperiment,
        summary_type=CounterfactualExperimentSummary,
        job_name="counterfactual",
    )
