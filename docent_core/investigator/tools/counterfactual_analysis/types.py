from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from docent.data_models import AgentRun
from docent_core.investigator.db.schemas.experiment import (
    SQLACounterfactualExperimentConfig,
    SQLACounterfactualExperimentResult,
    SQLAExperimentIdea,
)
from docent_core.investigator.tools.backends.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
)
from docent_core.investigator.tools.common.types import ExperimentStatus, Grade, generate_uid
from docent_core.investigator.tools.contexts.base_context import BaseContext
from docent_core.investigator.tools.judges.rubric_judge import RubricJudgeConfig
from docent_core.investigator.tools.policies.deterministic import DeterministicContextPolicyConfig


class ExperimentIdea(BaseModel):
    """
    Pydantic model for experiment idea.

    This is the idea for the *entire* experiment. For example, if the test were varying the
    language of the context, `idea` might be "Try changing the context to be another language."
    """

    id: str
    name: str
    idea: str

    @classmethod
    def from_sql(cls, idea: SQLAExperimentIdea) -> "ExperimentIdea":
        return cls(
            id=idea.id,
            name=idea.name,
            idea=idea.idea,
        )


class CounterfactualIdea(BaseModel):
    """
    A counterfactual idea.

    This is the idea for a single counterfactual. For example, if the test were varying the
    language of the context, `name` might be `language_spanish` and `description` might be
    "Convert the context to Spanish."
    """

    id: str = Field(default_factory=generate_uid)
    name: str
    description: str


class ParsedCounterfactualIdeas(BaseModel):
    """
    Event containing the parsed counterfactuals from the LLM response.

    This includes a map of counterfactual id -> counterfactual idea.
    """

    counterfactuals: dict[str, CounterfactualIdea]


class CounterfactualExperimentConfig(BaseModel):
    """Pydantic model for experiment configuration. This contains all the information needed to
    run the experiment, but not any results. This object should be immutable."""

    id: str = Field(default_factory=generate_uid)
    type: Literal["counterfactual"] = "counterfactual"
    workspace_id: str
    created_at: datetime
    judge_config: RubricJudgeConfig
    openai_compatible_backend: OpenAICompatibleBackendConfig
    idea: ExperimentIdea
    base_context: BaseContext

    # The number of counterfactual variations to generate
    num_counterfactuals: int = 1
    # The number of replicas to run for each counterfactual/base interaction.
    num_replicas: int = 1

    @classmethod
    def from_sql(
        cls, config: SQLACounterfactualExperimentConfig
    ) -> "CounterfactualExperimentConfig":
        return cls(
            id=config.id,
            workspace_id=config.workspace_id,
            created_at=config.created_at,
            judge_config=RubricJudgeConfig.from_sql(config.judge_config_obj),
            openai_compatible_backend=OpenAICompatibleBackendConfig.from_sql(
                config.openai_compatible_backend_obj
            ),
            idea=ExperimentIdea.from_sql(config.idea_obj),
            base_context=BaseContext.from_sql(config.base_context_obj),
            num_counterfactuals=config.num_counterfactuals,
            num_replicas=config.num_replicas,
        )


class CounterfactualAgentRunMetadata(BaseModel):
    """
    Agent run metadata for counterfactual experiment rollouts. It is also sent to the frontend
    for every update,so the information contained here must be lightweight. (Later, we could
    separate these, in case there is metadata that we streamed to the frontend but not exported to
    Docent.)
    """

    model: str
    counterfactual_id: str  # ID of the counterfactual
    counterfactual_name: str  # Name of the counterfactual being tested
    counterfactual_description: str  # Description of the counterfactual being tested
    replica_idx: int  # Index of the replica
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


class CounterfactualExperimentSummary(BaseModel):
    """
    A summary of information for a (potentially ongoing) counterfactual experiment.
    IMPORTANT: This will be streamed to the client very frequently! Thus, it must be very
    lightweight, and not include any large objects, such as full agent runs.
    """

    config: CounterfactualExperimentConfig
    experiment_status: ExperimentStatus

    # map of agent_run_id -> CounterfactualMetadata
    agent_run_metadata: Optional[dict[str, CounterfactualAgentRunMetadata]] = None

    # The output of the LLM that generated the counterfactual ideas and contexts.
    counterfactual_idea_output: Optional[str] = None

    # The output of all LLM calls to turn counterfactual ideas into BaseContexts.
    counterfactual_context_output: Optional[dict[str, str]] = None

    # The parsed counterfactual ideas from the LLM that generated the counterfactual ideas.
    parsed_counterfactual_ideas: Optional[ParsedCounterfactualIdeas] = None

    # Parsed policy configs for each counterfactual applied to the base context.
    # counterfactual_id -> policy config
    counterfactual_policy_configs: Optional[dict[str, DeterministicContextPolicyConfig]] = None
    base_policy_config: Optional[DeterministicContextPolicyConfig] = None

    # If the experiment has been saved to a Docent collection, this will be the collection id.
    docent_collection_id: Optional[str] = None

    # Full agent runs for any runs the client has explicitly subscribed to.
    # This is streamed only and is not persisted to the database.
    subscribed_agent_runs: Optional[dict[str, AgentRun]] = None


class CounterfactualExperimentResult(BaseModel):
    """
    Result of a counterfactual experiment. This contains ALL the information, including all
    agent runs and their metadata. Note that this object is very large, and should not be streamed
    to the frontend (except for slices, such as a single active agent run).
    """

    config: CounterfactualExperimentConfig
    experiment_status: ExperimentStatus

    # map of agent_run_id -> CounterfactualMetadata
    agent_run_metadata: Optional[dict[str, CounterfactualAgentRunMetadata]] = None

    # The output of the LLM that generated the counterfactual ideas and contexts.
    counterfactual_idea_output: Optional[str] = None

    # The output of all LLM calls to turn counterfactual ideas into BaseContexts.
    counterfactual_context_output: Optional[dict[str, str]] = None

    # The parsed counterfactual ideas from the LLM that generated the counterfactual ideas.
    parsed_counterfactual_ideas: Optional[ParsedCounterfactualIdeas] = None

    # Parsed policy configs for each counterfactual applied to the base context.
    # counterfactual_id -> policy config
    counterfactual_policy_configs: Optional[dict[str, DeterministicContextPolicyConfig]] = None
    base_policy_config: Optional[DeterministicContextPolicyConfig] = None

    # Heavy objects (not included in the summary)
    # map of agent_run_id -> AgentRun
    agent_runs: Optional[dict[str, AgentRun]] = None

    # If the experiment has been saved to a Docent collection, this will be the collection id.
    docent_collection_id: Optional[str] = None

    @property
    def id(self) -> str:
        # Note: there is a one-to-one mapping between experiment configs and results!
        # To re-run an experiment, you must clone the config and create a new result.
        return self.config.id

    def summary(self) -> "CounterfactualExperimentSummary":
        return CounterfactualExperimentSummary(
            config=self.config,
            experiment_status=self.experiment_status,
            agent_run_metadata=self.agent_run_metadata,
            counterfactual_idea_output=self.counterfactual_idea_output,
            counterfactual_context_output=self.counterfactual_context_output,
            parsed_counterfactual_ideas=self.parsed_counterfactual_ideas,
            counterfactual_policy_configs=self.counterfactual_policy_configs,
            base_policy_config=self.base_policy_config,
            docent_collection_id=self.docent_collection_id,
        )

    @classmethod
    def from_sql(
        cls, result: SQLACounterfactualExperimentResult
    ) -> "CounterfactualExperimentResult":
        """
        Create a CounterfactualExperimentResult from a SQLAlchemy result object.
        Note: This does NOT load agent runs from the collection - those need to be fetched separately.
        """
        return cls(
            config=CounterfactualExperimentConfig.from_sql(result.experiment_config),
            experiment_status=ExperimentStatus(
                status=result.status, progress=result.progress, start_time=result.created_at
            ),
            agent_run_metadata=result.agent_run_metadata,
            counterfactual_idea_output=result.counterfactual_idea_output,
            counterfactual_context_output=result.counterfactual_context_output,
            parsed_counterfactual_ideas=(
                ParsedCounterfactualIdeas(**result.parsed_counterfactual_ideas)
                if result.parsed_counterfactual_ideas
                else None
            ),
            counterfactual_policy_configs=result.counterfactual_policy_configs,
            base_policy_config=result.base_policy_config,
            agent_runs=None,  # Agent runs need to be loaded separately from the collection
            docent_collection_id=result.collection_id,
        )
