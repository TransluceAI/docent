from typing import Any, Callable, Coroutine

from docent_core._worker.constants import WorkerFunction
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.workers.centroid_assignment_worker import (
    centroid_assignment_job,
    clustering_job,
)
from docent_core.docent.workers.chat_worker import chat_job
from docent_core.docent.workers.embedding_worker import compute_embeddings
from docent_core.docent.workers.hodoscope_worker import hodoscope_analysis_job
from docent_core.docent.workers.refinement_worker import refinement_agent_job
from docent_core.docent.workers.rubric_job_worker import rubric_job
from docent_core.docent.workers.telemetry_worker import telemetry_processing_job

JOB_DISPATCHER_MAP: dict[str, Callable[[ViewContext, SQLAJob], Coroutine[Any, Any, None]]] = {
    WorkerFunction.RUBRIC_JOB.value: rubric_job,
    WorkerFunction.COMPUTE_EMBEDDINGS.value: compute_embeddings,
    WorkerFunction.CENTROID_ASSIGNMENT_JOB.value: centroid_assignment_job,
    WorkerFunction.REFINEMENT_AGENT_JOB.value: refinement_agent_job,
    WorkerFunction.CHAT_JOB.value: chat_job,
    WorkerFunction.CLUSTERING_JOB.value: clustering_job,
    WorkerFunction.TELEMETRY_PROCESSING_JOB.value: telemetry_processing_job,
    WorkerFunction.HODOSCOPE_ANALYSIS.value: hodoscope_analysis_job,
}
