from enum import Enum

WORKER_QUEUE_NAME = "docent_worker_queue"
TELEMETRY_PROCESSING_QUEUE_NAME = "docent_worker_queue:telemetry_processing"
TELEMETRY_INGEST_QUEUE_NAME = "docent_worker_queue:telemetry_ingest"
# TODO(mengk) we should really consider making our jobs not... this long.
JOB_TIMEOUT_SECONDS = 20 * 60  # 20 minutes


class WorkerFunction(str, Enum):
    RUBRIC_JOB = "rubric_job"
    CENTROID_ASSIGNMENT_JOB = "centroid_assignment_job"  # Deprecated
    REFINEMENT_AGENT_JOB = "refinement_agent_job"
    CLUSTERING_JOB = "clustering_job"
    CHAT_JOB = "chat_job"
    TELEMETRY_PROCESSING_JOB = "telemetry_processing_job"
    TELEMETRY_INGEST_JOB = "telemetry_ingest_job"
    COUNTERFACTUAL_EXPERIMENT_JOB = "counterfactual_experiment_job"
    SIMPLE_ROLLOUT_EXPERIMENT_JOB = "simple_rollout_experiment_job"
    REFLECTION_JOB = "reflection_job"


JOB_QUEUE_OVERRIDES: dict[str, str] = {
    WorkerFunction.TELEMETRY_PROCESSING_JOB.value: TELEMETRY_PROCESSING_QUEUE_NAME,
    WorkerFunction.TELEMETRY_INGEST_JOB.value: TELEMETRY_INGEST_QUEUE_NAME,
}

KNOWN_WORKER_QUEUES: frozenset[str] = frozenset([WORKER_QUEUE_NAME, *JOB_QUEUE_OVERRIDES.values()])


def get_queue_name_for_job_type(job_type: str | WorkerFunction) -> str:
    """Map a job type to a queue name."""
    key = job_type.value if isinstance(job_type, WorkerFunction) else job_type
    return JOB_QUEUE_OVERRIDES.get(key, WORKER_QUEUE_NAME)


def validate_worker_queue_name(queue_name: str) -> str:
    """Ensure worker processes only bind to queues we understand."""
    if queue_name not in KNOWN_WORKER_QUEUES:
        expected = ", ".join(sorted(KNOWN_WORKER_QUEUES))
        raise ValueError(f"Unknown worker queue '{queue_name}'. Expected one of: {expected}")
    return queue_name
