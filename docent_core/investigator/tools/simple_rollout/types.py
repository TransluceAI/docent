"""Type definitions for simple rollout experiments."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from docent.data_models import AgentRun
from docent_core.investigator.db.schemas.experiment import (
    SQLASimpleRolloutExperimentConfig,
    SQLASimpleRolloutExperimentResult,
)
from docent_core.investigator.tools.backends.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
)
from docent_core.investigator.tools.common.types import ExperimentStatus, Grade, generate_uid
from docent_core.investigator.tools.contexts.base_context import BaseContext
from docent_core.investigator.tools.judges.rubric_judge import RubricJudgeConfig
from docent_core.investigator.tools.policies.deterministic import DeterministicContextPolicyConfig


class SimpleRolloutExperimentConfig(BaseModel):
    """
    Configuration for a simple rollout experiment.

    This contains all information needed to run the experiment, but not any results.
    This object should be immutable.
    """

    id: str = Field(default_factory=generate_uid)
    type: Literal["simple_rollout"] = "simple_rollout"
    workspace_id: str
    created_at: datetime
    judge_config: Optional[RubricJudgeConfig] = None
    openai_compatible_backends: list[OpenAICompatibleBackendConfig]
    base_context: BaseContext

    # Number of replicas to run
    num_replicas: int = 1
    # Maximum number of turns
    max_turns: int = 10

    @field_validator("openai_compatible_backends")
    @classmethod
    def validate_backends(
        cls, v: list[OpenAICompatibleBackendConfig]
    ) -> list[OpenAICompatibleBackendConfig]:
        """Validate that at least 1 and at most 10 backends are provided."""
        if len(v) < 1:
            raise ValueError("At least one backend must be provided")
        if len(v) > 10:
            raise ValueError("At most 10 backends can be provided")
        return v

    @classmethod
    def from_sql(cls, config: SQLASimpleRolloutExperimentConfig) -> "SimpleRolloutExperimentConfig":
        """Build from SQL model."""

        # These should be loaded via eager loading or separate queries
        base_context = config.base_context_obj
        backends = config.openai_compatible_backend_objs
        judge = config.judge_config_obj if config.judge_config_id else None

        return cls(
            id=config.id,
            workspace_id=config.workspace_id,
            created_at=config.created_at,
            judge_config=RubricJudgeConfig.from_sql(judge) if judge else None,
            openai_compatible_backends=[
                OpenAICompatibleBackendConfig.from_sql(backend) for backend in backends
            ],
            base_context=BaseContext.from_sql(base_context),
            num_replicas=config.num_replicas,
            max_turns=config.max_turns,
        )


class SimpleRolloutAgentRunMetadata(BaseModel):
    """
    Agent run metadata for simple rollout experiments.

    This is sent to the frontend for every update, so it must be lightweight.
    """

    model: str
    backend_name: str
    replica_idx: int
    grade: Optional[Grade] = None

    # Simple per-run state for UI display
    state: Literal["in_progress", "completed", "errored"] = "in_progress"

    error_type: Optional[
        Literal[
            "policy_error",
            "subject_model_error",
            "judge_error",
            "network_error",
            "timeout_error",
            "unknown_error",
        ]
    ] = None
    error_message: Optional[str] = None  # Server-controlled, sanitized error message


class SimpleRolloutExperimentSummary(BaseModel):
    """
    A summary of information for a (potentially ongoing) simple rollout experiment.

    IMPORTANT: This will be streamed to the client very frequently! Thus, it must be very
    lightweight, and not include any large objects, such as full agent runs.
    """

    config: SimpleRolloutExperimentConfig
    experiment_status: ExperimentStatus

    # Map of agent_run_id -> metadata
    agent_run_metadata: Optional[dict[str, SimpleRolloutAgentRunMetadata]] = None

    # Policy config used for all rollouts
    base_policy_config: Optional[DeterministicContextPolicyConfig] = None

    # If the experiment has been saved to a Docent collection, this will be the collection id.
    docent_collection_id: Optional[str] = None

    # This is streamed only and is not persisted to the database.
    subscribed_agent_runs: Optional[dict[str, AgentRun]] = None


class SimpleRolloutExperimentResult(BaseModel):
    """
    Result of a simple rollout experiment.

    This contains ALL the information, including all agent runs and their metadata.
    Note that this object is very large, and should not be streamed to the frontend
    (except for slices, such as a single active agent run).
    """

    config: SimpleRolloutExperimentConfig
    experiment_status: ExperimentStatus

    # Map of agent_run_id -> metadata
    agent_run_metadata: Optional[dict[str, SimpleRolloutAgentRunMetadata]] = None

    # Policy config used for all rollouts
    base_policy_config: Optional[DeterministicContextPolicyConfig] = None

    # Heavy objects (not included in the summary)
    # Map of agent_run_id -> AgentRun
    agent_runs: Optional[dict[str, AgentRun]] = None

    # If the experiment has been saved to a Docent collection, this will be the collection id.
    docent_collection_id: Optional[str] = None

    @property
    def id(self) -> str:
        """Return the config ID as the experiment ID."""
        return self.config.id

    def summary(self) -> SimpleRolloutExperimentSummary:
        """
        Get a lightweight summary suitable for streaming.

        This excludes heavy objects like full agent runs.
        """
        return SimpleRolloutExperimentSummary(
            config=self.config,
            experiment_status=self.experiment_status,
            agent_run_metadata=self.agent_run_metadata,
            base_policy_config=self.base_policy_config,
            docent_collection_id=self.docent_collection_id,
            # subscribed_agent_runs is populated by the worker when streaming
        )

    @classmethod
    def from_sql(cls, result: SQLASimpleRolloutExperimentResult) -> "SimpleRolloutExperimentResult":
        """Build from SQL model."""

        # Build the config (this needs the related objects to be loaded)
        config = SimpleRolloutExperimentConfig.from_sql(result.experiment_config)

        # Parse metadata if it exists
        agent_run_metadata = None
        if result.agent_run_metadata:
            agent_run_metadata = {
                run_id: SimpleRolloutAgentRunMetadata(**meta_dict)
                for run_id, meta_dict in result.agent_run_metadata.items()
            }

        # Parse base policy config if it exists
        base_policy_config = None
        if result.base_policy_config:
            base_policy_config = DeterministicContextPolicyConfig(**result.base_policy_config)

        return cls(
            config=config,
            experiment_status=ExperimentStatus(
                status=result.status,
                progress=result.progress or 0.0,
                start_time=result.created_at,
                docent_collection_id=result.collection_id,
            ),
            agent_run_metadata=agent_run_metadata,
            base_policy_config=base_policy_config,
            agent_runs=None,  # Would need to be loaded separately from collection
            docent_collection_id=result.collection_id,
        )
