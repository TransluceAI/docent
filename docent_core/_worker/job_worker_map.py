from typing import Any, Callable, Coroutine, Union

from docent_core._worker.constants import WorkerFunction
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.workers.centroid_assignment_worker import (
    centroid_assignment_job,
    clustering_job,
)
from docent_core.docent.workers.chat_worker import chat_job
from docent_core.docent.workers.embedding_worker import compute_embeddings
from docent_core.docent.workers.refinement_worker import refinement_agent_job
from docent_core.docent.workers.reflection_worker import reflection_job
from docent_core.docent.workers.rubric_job_worker import rubric_job
from docent_core.docent.workers.telemetry_worker import telemetry_processing_job
from docent_core.investigator.db.contexts import WorkspaceContext
from docent_core.investigator.workers.counterfactual_experiment_worker import (
    counterfactual_experiment_job,
)
from docent_core.investigator.workers.simple_rollout_experiment_worker import (
    simple_rollout_experiment_job,
)

ViewContextJob = Callable[[ViewContext, SQLAJob], Coroutine[Any, Any, None]]
WorkspaceContextJob = Callable[[WorkspaceContext, SQLAJob], Coroutine[Any, Any, None]]

JOB_DISPATCHER_MAP: dict[str, Union[ViewContextJob, WorkspaceContextJob]] = {
    WorkerFunction.RUBRIC_JOB.value: rubric_job,
    WorkerFunction.COMPUTE_EMBEDDINGS.value: compute_embeddings,
    WorkerFunction.CENTROID_ASSIGNMENT_JOB.value: centroid_assignment_job,
    WorkerFunction.REFINEMENT_AGENT_JOB.value: refinement_agent_job,
    WorkerFunction.CHAT_JOB.value: chat_job,
    WorkerFunction.CLUSTERING_JOB.value: clustering_job,
    WorkerFunction.REFLECTION_JOB.value: reflection_job,
    WorkerFunction.TELEMETRY_PROCESSING_JOB.value: telemetry_processing_job,
    WorkerFunction.COUNTERFACTUAL_EXPERIMENT_JOB.value: counterfactual_experiment_job,
    WorkerFunction.SIMPLE_ROLLOUT_EXPERIMENT_JOB.value: simple_rollout_experiment_job,
}
