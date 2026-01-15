from typing import Any, Callable, Coroutine

from docent_core._worker.constants import WorkerFunction
from docent_core.docent.db.schemas.tables import SQLAJob
from docent_core.docent.workers.agent_run_ingest_worker import agent_run_ingest_job
from docent_core.docent.workers.centroid_assignment_worker import (
    centroid_assignment_job,
    clustering_job,
)
from docent_core.docent.workers.chat_worker import chat_job
from docent_core.docent.workers.llm_result_worker import llm_result_job
from docent_core.docent.workers.refinement_worker import refinement_agent_job
from docent_core.docent.workers.reflection_worker import reflection_job
from docent_core.docent.workers.rubric_job_worker import rubric_job
from docent_core.docent.workers.telemetry_ingest_worker import telemetry_ingest_job
from docent_core.docent.workers.telemetry_worker import telemetry_processing_job

# Job contexts differ per worker, so the dispatcher keeps the callable context parameter generic.
JobHandler = Callable[[Any, SQLAJob], Coroutine[Any, Any, None]]

JOB_DISPATCHER_MAP: dict[str, JobHandler] = {
    WorkerFunction.RUBRIC_JOB.value: rubric_job,
    WorkerFunction.CENTROID_ASSIGNMENT_JOB.value: centroid_assignment_job,
    WorkerFunction.REFINEMENT_AGENT_JOB.value: refinement_agent_job,
    WorkerFunction.CHAT_JOB.value: chat_job,
    WorkerFunction.CLUSTERING_JOB.value: clustering_job,
    WorkerFunction.REFLECTION_JOB.value: reflection_job,
    WorkerFunction.LLM_RESULT_JOB.value: llm_result_job,
    WorkerFunction.AGENT_RUN_INGEST_JOB.value: agent_run_ingest_job,
    WorkerFunction.TELEMETRY_INGEST_JOB.value: telemetry_ingest_job,
    WorkerFunction.TELEMETRY_PROCESSING_JOB.value: telemetry_processing_job,
}
