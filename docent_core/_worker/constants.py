from enum import Enum

WORKER_QUEUE_NAME = "docent_worker_queue"


class WorkerFunction(str, Enum):
    """TODO(mengk): this is dumb but required because of a circular import. ugh."""

    COMPUTE_SEARCH = "compute_search"
    COMPUTE_EMBEDDINGS = "compute_embeddings"
    RUBRIC_JOB = "rubric_job"
    CENTROID_ASSIGNMENT_JOB = "centroid_assignment_job"
