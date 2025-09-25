import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent._log_util import get_logger
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.tables import TABLE_USER

logger = get_logger(__name__)

# Table names
TABLE_INVESTIGATOR_WORKSPACE = "investigator_workspaces"
TABLE_COUNTERFACTUAL_EXPERIMENT_CONFIG = "counterfactual_experiment_configs"
TABLE_COUNTERFACTUAL_EXPERIMENT_RESULT = "counterfactual_experiment_results"
TABLE_JUDGE_CONFIG = "judge_configs"
TABLE_OPENAI_COMPATIBLE_BACKEND = "openai_compatible_backends"
TABLE_EXPERIMENT_IDEA = "experiment_ideas"
TABLE_BASE_CONTEXT = "base_contexts"
TABLE_TMP_INVESTIGATOR_AUTHORIZED_USERS = "tmp_investigator_authorized_users"


def generate_uid() -> str:
    """Generate a unique identifier."""
    return str(uuid4())


# =====================
# SQLAlchemy Models
# =====================


class SQLAInvestigatorWorkspace(SQLABase):
    """SQL schema for investigator workspaces - similar to collections in docent."""

    __tablename__ = TABLE_INVESTIGATOR_WORKSPACE

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=True)
    description = mapped_column(Text, nullable=True)

    # User who created this workspace
    created_by = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Relationships to owned entities
    judge_configs: Mapped[list["SQLAJudgeConfig"]] = relationship(
        "SQLAJudgeConfig", back_populates="workspace", cascade="all, delete-orphan"
    )
    openai_compatible_backends: Mapped[list["SQLAOpenAICompatibleBackend"]] = relationship(
        "SQLAOpenAICompatibleBackend", back_populates="workspace", cascade="all, delete-orphan"
    )
    experiment_ideas: Mapped[list["SQLAExperimentIdea"]] = relationship(
        "SQLAExperimentIdea", back_populates="workspace", cascade="all, delete-orphan"
    )
    base_contexts: Mapped[list["SQLABaseContext"]] = relationship(
        "SQLABaseContext", back_populates="workspace", cascade="all, delete-orphan"
    )
    experiment_configs: Mapped[list["SQLACounterfactualExperimentConfig"]] = relationship(
        "SQLACounterfactualExperimentConfig",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class SQLAJudgeConfig(SQLABase):
    """SQL schema for judge configurations."""

    __tablename__ = TABLE_JUDGE_CONFIG

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=True)
    rubric = mapped_column(Text, nullable=False)

    # Workspace that owns this config
    workspace_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_INVESTIGATOR_WORKSPACE}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Soft delete - null means active, timestamp means deleted
    deleted_at = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    workspace: Mapped["SQLAInvestigatorWorkspace"] = relationship(
        "SQLAInvestigatorWorkspace", back_populates="judge_configs"
    )
    experiment_configs: Mapped[list["SQLACounterfactualExperimentConfig"]] = relationship(
        "SQLACounterfactualExperimentConfig", back_populates="judge_config_obj"
    )


class SQLAOpenAICompatibleBackend(SQLABase):
    """SQL schema for OpenAI-compatible backend configurations."""

    __tablename__ = TABLE_OPENAI_COMPATIBLE_BACKEND

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=False)
    provider = mapped_column(Text, nullable=False)  # openai, anthropic, google, custom
    model = mapped_column(Text, nullable=False)
    api_key = mapped_column(Text, nullable=True)
    base_url = mapped_column(Text, nullable=True)

    # Workspace that owns this config
    workspace_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_INVESTIGATOR_WORKSPACE}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Soft delete - null means active, timestamp means deleted
    deleted_at = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    workspace: Mapped["SQLAInvestigatorWorkspace"] = relationship(
        "SQLAInvestigatorWorkspace", back_populates="openai_compatible_backends"
    )
    experiment_configs: Mapped[list["SQLACounterfactualExperimentConfig"]] = relationship(
        "SQLACounterfactualExperimentConfig", back_populates="openai_compatible_backend_obj"
    )


class SQLAExperimentIdea(SQLABase):
    """SQL schema for experiment ideas."""

    __tablename__ = TABLE_EXPERIMENT_IDEA

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=False)
    idea = mapped_column(Text, nullable=False)

    # Workspace that owns this idea
    workspace_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_INVESTIGATOR_WORKSPACE}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Soft delete - null means active, timestamp means deleted
    deleted_at = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    workspace: Mapped["SQLAInvestigatorWorkspace"] = relationship(
        "SQLAInvestigatorWorkspace", back_populates="experiment_ideas"
    )
    experiment_configs: Mapped[list["SQLACounterfactualExperimentConfig"]] = relationship(
        "SQLACounterfactualExperimentConfig", back_populates="idea_obj"
    )


class SQLABaseContext(SQLABase):
    """SQL schema for base contexts."""

    __tablename__ = TABLE_BASE_CONTEXT

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=False)

    # Store the prompt as JSONB (list of messages)
    prompt = mapped_column(JSONB, nullable=False)

    tools = mapped_column(JSONB, nullable=True)

    # Workspace that owns this interaction
    workspace_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_INVESTIGATOR_WORKSPACE}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Soft delete - null means active, timestamp means deleted
    deleted_at = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    workspace: Mapped["SQLAInvestigatorWorkspace"] = relationship(
        "SQLAInvestigatorWorkspace", back_populates="base_contexts"
    )
    experiment_configs: Mapped[list["SQLACounterfactualExperimentConfig"]] = relationship(
        "SQLACounterfactualExperimentConfig", back_populates="base_context_obj"
    )

    def to_json_array_str(self) -> str:
        """
        Formats the interaction as a list of messages, useful for passing to an LLM.
        """
        return json.dumps(self.prompt, indent=4)


class SQLACounterfactualExperimentConfig(SQLABase):
    """SQLAlchemy model for counterfactual experiment configurations."""

    __tablename__ = TABLE_COUNTERFACTUAL_EXPERIMENT_CONFIG

    id = mapped_column(String(36), primary_key=True)

    # Workspace that owns this experiment config
    workspace_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_INVESTIGATOR_WORKSPACE}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Foreign keys to related configs (all must be in same workspace)
    judge_config_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_JUDGE_CONFIG}.id"), nullable=False, index=True
    )
    openai_compatible_backend_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_OPENAI_COMPATIBLE_BACKEND}.id"), nullable=False, index=True
    )
    idea_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_EXPERIMENT_IDEA}.id"), nullable=False, index=True
    )
    base_context_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_BASE_CONTEXT}.id"), nullable=False, index=True
    )

    # Experiment parameters
    num_counterfactuals = mapped_column(Integer, nullable=False, default=1)
    num_replicas = mapped_column(Integer, nullable=False, default=1)
    max_turns = mapped_column(Integer, nullable=False, default=1)

    # Soft delete - null means active, timestamp means deleted
    deleted_at = mapped_column(DateTime, nullable=True, index=True)

    # Relationships
    workspace: Mapped["SQLAInvestigatorWorkspace"] = relationship(
        "SQLAInvestigatorWorkspace", back_populates="experiment_configs"
    )
    judge_config_obj: Mapped["SQLAJudgeConfig"] = relationship(
        "SQLAJudgeConfig", back_populates="experiment_configs"
    )
    openai_compatible_backend_obj: Mapped["SQLAOpenAICompatibleBackend"] = relationship(
        "SQLAOpenAICompatibleBackend", back_populates="experiment_configs"
    )
    idea_obj: Mapped["SQLAExperimentIdea"] = relationship(
        "SQLAExperimentIdea", back_populates="experiment_configs"
    )
    base_context_obj: Mapped["SQLABaseContext"] = relationship(
        "SQLABaseContext", back_populates="experiment_configs"
    )

    # Relationship to experiment result (one-to-one)
    experiment_result: Mapped["SQLACounterfactualExperimentResult"] = relationship(
        "SQLACounterfactualExperimentResult",
        back_populates="experiment_config",
        uselist=False,
        cascade="all, delete-orphan",
    )


class SQLACounterfactualExperimentResult(SQLABase):
    """SQLAlchemy model for counterfactual experiment results."""

    __tablename__ = TABLE_COUNTERFACTUAL_EXPERIMENT_RESULT

    id = mapped_column(String(36), primary_key=True)

    # Foreign key to the experiment config (one-to-one)
    experiment_config_id = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_COUNTERFACTUAL_EXPERIMENT_CONFIG}.id"),
        nullable=False,
        unique=True,  # Enforce one-to-one relationship
        index=True,
    )

    # Link to docent collection containing agent runs
    collection_id = mapped_column(
        String(36),
        ForeignKey("collections.id"),  # Reference to docent's collection table
        nullable=True,  # Nullable initially, populated when agent runs are stored
        index=True,
    )

    # Experiment status
    status = mapped_column(String(50), nullable=False, default="in_progress")
    progress = mapped_column(Integer, nullable=False, default=0)

    # Lightweight metadata (streamed frequently)
    # Store the agent run metadata map as JSONB
    agent_run_metadata = mapped_column(JSONB, nullable=True)

    # Store the counterfactual generation outputs
    counterfactual_idea_output = mapped_column(Text, nullable=True)
    counterfactual_context_output = mapped_column(JSONB, nullable=True)  # dict[str, str]
    parsed_counterfactual_ideas = mapped_column(JSONB, nullable=True)

    # Store policy configs
    counterfactual_policy_configs = mapped_column(
        JSONB, nullable=True
    )  # dict[str, DeterministicContextPolicyConfig]
    base_policy_config = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    completed_at = mapped_column(DateTime, nullable=True)

    # Relationship back to experiment config
    experiment_config: Mapped["SQLACounterfactualExperimentConfig"] = relationship(
        "SQLACounterfactualExperimentConfig", back_populates="experiment_result"
    )


class SQLATmpInvestigatorAuthorizedUser(SQLABase):
    """SQL schema for temporary investigator authorized users whitelist."""

    __tablename__ = TABLE_TMP_INVESTIGATOR_AUTHORIZED_USERS

    id = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    # User who is authorized to access investigator
    user_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True, unique=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
