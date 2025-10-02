"""Type definitions for simple rollout experiments."""

import hashlib
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from docent.data_models import AgentRun
from docent_core.investigator.db.schemas.experiment import (
    SQLASimpleRolloutExperimentConfig,
    SQLASimpleRolloutExperimentResult,
)
from docent_core.investigator.tools.backends.anthropic_compatible_backend import (
    AnthropicCompatibleBackendConfig,
)
from docent_core.investigator.tools.backends.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
)
from docent_core.investigator.tools.backends.types import BackendConfig
from docent_core.investigator.tools.common.signature_utils import update_hash_with_agent_run
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
    backends: list[BackendConfig]  # Can be mixed OpenAI and Anthropic backends
    base_context: BaseContext

    # Number of replicas to run
    num_replicas: int = 1
    # Maximum number of turns
    max_turns: int = 10

    @field_validator("backends")
    @classmethod
    def validate_backends(cls, v: list[BackendConfig]) -> list[BackendConfig]:
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
        openai_backends = config.openai_compatible_backend_objs
        anthropic_backends = config.anthropic_compatible_backend_objs
        judge = config.judge_config_obj if config.judge_config_id else None

        # Combine both backend types into a single list
        backends: list[BackendConfig] = [
            OpenAICompatibleBackendConfig.from_sql(backend) for backend in openai_backends
        ] + [AnthropicCompatibleBackendConfig.from_sql(backend) for backend in anthropic_backends]

        return cls(
            id=config.id,
            workspace_id=config.workspace_id,
            created_at=config.created_at,
            judge_config=RubricJudgeConfig.from_sql(judge) if judge else None,
            backends=backends,
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
    # Now just a float; Grade object is automatically converted via validator for backwards compatibility
    grade: Optional[float] = None

    @field_validator("grade", mode="before")
    @classmethod
    def _extract_grade_from_object(cls, v: Any) -> float | None:
        """Convert Grade object to float for backwards compatibility."""
        if v is None:
            return None
        # If it's a Grade object (has a 'grade' attribute), extract the float
        if isinstance(v, Grade):
            return float(v.grade)
        # If it's a dict with 'grade' key (from serialization), extract the float
        if isinstance(v, dict) and "grade" in v:
            return float(v["grade"])  # type: ignore[arg-type]
        # If it's already a float or int, return as float
        if isinstance(v, (float, int)):
            return float(v)
        # Otherwise try to convert to float
        return float(v)  # type: ignore[arg-type]

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

    def compute_signature(self, subscribed_run_ids: set[str]) -> bytes:
        """Compute a fast hash-based signature for change detection.

        This signature changes whenever any relevant state changes, including:
        - Experiment status, progress, or errors
        - Agent run metadata (state, grade)
        - Collection ID
        - Subscribed run transcript data (message counts and content lengths)

        Args:
            subscribed_run_ids: Set of agent run IDs to include detailed transcript info for

        Returns:
            MD5 digest representing the current state (16 bytes)
        """
        h = hashlib.md5()

        # Status (changes frequently during execution)
        h.update(self.experiment_status.status.encode())
        h.update(str(round(self.experiment_status.progress or 0.0, 3)).encode())
        h.update(b"1" if self.experiment_status.error_message else b"0")

        # Agent run metadata - state and grade
        if self.agent_run_metadata:
            for run_id in sorted(self.agent_run_metadata.keys()):
                m = self.agent_run_metadata[run_id]
                h.update(run_id.encode())
                h.update((m.state or "").encode())
                if m.grade is not None:
                    h.update(str(m.grade).encode())

        # Collection ID
        if self.docent_collection_id:
            h.update(self.docent_collection_id.encode())

        # Subscribed runs - transcript message counts and last message length
        if self.agent_runs:
            for run_id in sorted(subscribed_run_ids):
                run = self.agent_runs.get(run_id)
                if run:
                    h.update(run_id.encode())
                    h.update(str(len(run.transcripts)).encode())
                    update_hash_with_agent_run(h, run)

        return h.digest()

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
