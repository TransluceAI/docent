from enum import Enum
from typing import Any, Callable, Coroutine

from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.tables import SQLAJob
from docent_core.docent.workers.centroid_assignment_worker import centroid_assignment_job
from docent_core.docent.workers.embedding_worker import compute_embeddings
from docent_core.docent.workers.rubric_job_worker import rubric_job

WORKER_QUEUE_NAME = "docent_worker_queue"


class WorkerFunction(str, Enum):
    """TODO(mengk): this is dumb but required because of a circular import. ugh."""

    COMPUTE_EMBEDDINGS = "compute_embeddings"
    RUBRIC_JOB = "rubric_job"
    CENTROID_ASSIGNMENT_JOB = "centroid_assignment_job"


JOB_DISPATCHER_MAP: dict[str, Callable[[ViewContext, SQLAJob], Coroutine[Any, Any, None]]] = {
    WorkerFunction.RUBRIC_JOB.value: rubric_job,
    WorkerFunction.COMPUTE_EMBEDDINGS.value: compute_embeddings,
    WorkerFunction.CENTROID_ASSIGNMENT_JOB.value: centroid_assignment_job,
}
