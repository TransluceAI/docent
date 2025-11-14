from enum import Enum

WORKER_QUEUE_NAME = "docent_worker_queue"
# TODO(mengk) we should really consider making our jobs not... this long.
JOB_TIMEOUT_SECONDS = 20 * 60  # 20 minutes


class WorkerFunction(str, Enum):
    RUBRIC_JOB = "rubric_job"
    CENTROID_ASSIGNMENT_JOB = "centroid_assignment_job"  # Deprecated
    REFINEMENT_AGENT_JOB = "refinement_agent_job"
    CLUSTERING_JOB = "clustering_job"
    CHAT_JOB = "chat_job"
    TELEMETRY_PROCESSING_JOB = "telemetry_processing_job"
    COUNTERFACTUAL_EXPERIMENT_JOB = "counterfactual_experiment_job"
    SIMPLE_ROLLOUT_EXPERIMENT_JOB = "simple_rollout_experiment_job"
    REFLECTION_JOB = "reflection_job"
