from enum import Enum

WORKER_QUEUE_NAME = "docent_worker_queue"
TELEMETRY_PROCESSING_QUEUE_NAME = "docent_worker_queue:telemetry_processing"
TELEMETRY_INGEST_QUEUE_NAME = "docent_worker_queue:telemetry_ingest"
# TODO(mengk) we should really consider making our jobs not... this long.
DEFAULT_JOB_TIMEOUT_SECONDS = 20 * 60  # 20 minutes


class WorkerFunction(str, Enum):
    # Rubrics and clustering
    RUBRIC_JOB = "rubric_job"
    CENTROID_ASSIGNMENT_JOB = "centroid_assignment_job"  # Deprecated
    CLUSTERING_JOB = "clustering_job"
    REFLECTION_JOB = "reflection_job"
    # LLM Results
    LLM_RESULT_JOB = "llm_result_job"
    # Agent and chat
    REFINEMENT_AGENT_JOB = "refinement_agent_job"
    CHAT_JOB = "chat_job"
    # Ingestion
    TELEMETRY_PROCESSING_JOB = "telemetry_processing_job"
    TELEMETRY_INGEST_JOB = "telemetry_ingest_job"
    AGENT_RUN_INGEST_JOB = "agent_run_ingest_job"


# Tune per-job timeouts here; defaults keep existing behavior.
JOB_TIMEOUT_SECONDS_BY_TYPE: dict[str, int] = {
    # Rubrics and clustering
    WorkerFunction.RUBRIC_JOB.value: 60 * 60,  # 1 hour
    WorkerFunction.CENTROID_ASSIGNMENT_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
    WorkerFunction.CLUSTERING_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
    WorkerFunction.REFLECTION_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
    # Agent and chat
    WorkerFunction.REFINEMENT_AGENT_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
    WorkerFunction.CHAT_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
    # Telemetry
    WorkerFunction.TELEMETRY_PROCESSING_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
    WorkerFunction.TELEMETRY_INGEST_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
    WorkerFunction.AGENT_RUN_INGEST_JOB.value: DEFAULT_JOB_TIMEOUT_SECONDS,
}


def get_job_timeout_seconds(job_type: str | WorkerFunction) -> int:
    key = job_type.value if isinstance(job_type, WorkerFunction) else job_type
    return JOB_TIMEOUT_SECONDS_BY_TYPE.get(key, DEFAULT_JOB_TIMEOUT_SECONDS)


def get_arq_job_timeout_seconds() -> int:
    return max([DEFAULT_JOB_TIMEOUT_SECONDS, *JOB_TIMEOUT_SECONDS_BY_TYPE.values()])


JOB_QUEUE_OVERRIDES: dict[str, str] = {
    WorkerFunction.TELEMETRY_PROCESSING_JOB.value: TELEMETRY_PROCESSING_QUEUE_NAME,
    WorkerFunction.TELEMETRY_INGEST_JOB.value: TELEMETRY_INGEST_QUEUE_NAME,
    WorkerFunction.AGENT_RUN_INGEST_JOB.value: TELEMETRY_INGEST_QUEUE_NAME,
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
