from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Literal, Sequence
from uuid import uuid4

from sqlalchemy import delete, select, text, update

from docent._log_util import get_logger
from docent_core._db_service.db import DocentDB
from docent_core.docent.db.schemas.auth_models import User
from docent_core.investigator.db.schemas.experiment import (
    SQLABaseContext,
    SQLACounterfactualExperimentConfig,
    SQLAExperimentIdea,
    SQLAInvestigatorWorkspace,
    SQLAJudgeConfig,
    SQLAOpenAICompatibleBackend,
    SQLASimpleRolloutExperimentConfig,
)

logger = get_logger(__name__)


class InvestigatorMonoService:
    """Service for managing investigator-related operations."""

    def __init__(self, db: DocentDB):
        self.db = db

    @classmethod
    async def init(cls):
        """Initialize the InvestigatorMonoService with a database connection."""
        db = await DocentDB.init()
        return cls(db)

    #######################
    # Workspaces          #
    #######################

    async def create_workspace(
        self,
        user: User,
        workspace_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a new investigator workspace (similar to collections in docent)."""
        workspace_id = workspace_id or str(uuid4())

        async with self.db.session() as session:
            session.add(
                SQLAInvestigatorWorkspace(
                    id=workspace_id,
                    name=name,
                    description=description,
                    created_by=user.id,
                )
            )

        logger.info(f"Created InvestigatorWorkspace with ID: {workspace_id}")
        return workspace_id

    async def get_workspaces(self, user: User) -> Sequence[SQLAInvestigatorWorkspace]:
        """List workspaces for a user."""
        async with self.db.session() as session:
            query = (
                select(SQLAInvestigatorWorkspace)
                .where(SQLAInvestigatorWorkspace.created_by == user.id)
                .order_by(SQLAInvestigatorWorkspace.created_at.desc())
            )
            result = await session.execute(query)
            return result.scalars().all()

    async def get_workspace(self, workspace_id: str) -> SQLAInvestigatorWorkspace | None:
        """Get a single workspace by ID."""
        async with self.db.session() as session:
            query = select(SQLAInvestigatorWorkspace).where(
                SQLAInvestigatorWorkspace.id == workspace_id
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def workspace_exists(self, workspace_id: str) -> bool:
        """Check if a workspace exists."""
        async with self.db.session() as session:
            query = select(SQLAInvestigatorWorkspace.id).where(
                SQLAInvestigatorWorkspace.id == workspace_id
            )
            result = await session.execute(query)
            return result.scalar_one_or_none() is not None

    async def update_workspace(
        self,
        workspace_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> bool:
        """Update a workspace's name and/or description."""

        async with self.db.session() as session:
            stmt = update(SQLAInvestigatorWorkspace).where(
                SQLAInvestigatorWorkspace.id == workspace_id
            )

            updates = {}
            if name is not None:
                updates["name"] = name
            if description is not None:
                updates["description"] = description

            if not updates:
                return True  # Nothing to update

            stmt = stmt.values(**updates)
            result = await session.execute(stmt)
            await session.commit()

            updated = result.rowcount > 0
            if updated:
                logger.info(f"Updated InvestigatorWorkspace with ID: {workspace_id}")
            return updated

    async def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace (cascades to all owned entities)."""
        async with self.db.session() as session:
            result = await session.execute(
                delete(SQLAInvestigatorWorkspace).where(
                    SQLAInvestigatorWorkspace.id == workspace_id
                )
            )
            await session.commit()
            deleted = result.rowcount > 0
            if deleted:
                logger.info(f"Deleted InvestigatorWorkspace with ID: {workspace_id}")
            return deleted

    async def user_owns_workspace(self, user: User, workspace_id: str) -> bool:
        """Check if a user owns a workspace."""
        async with self.db.session() as session:
            query = select(SQLAInvestigatorWorkspace.created_by).where(
                SQLAInvestigatorWorkspace.id == workspace_id
            )
            result = await session.execute(query)
            owner_id = result.scalar_one_or_none()
            return owner_id == user.id if owner_id else False

    #######################
    # Judge Configs       #
    #######################

    async def create_judge_config(
        self,
        workspace_id: str,
        name: str | None,
        rubric: str,
        judge_config_id: str | None = None,
    ) -> str:
        """Create a new judge config in a workspace."""
        judge_config_id = judge_config_id or str(uuid4())

        async with self.db.session() as session:
            session.add(
                SQLAJudgeConfig(
                    id=judge_config_id,
                    name=name,
                    rubric=rubric,
                    workspace_id=workspace_id,
                )
            )

        logger.info(f"Created JudgeConfig with ID: {judge_config_id} in workspace: {workspace_id}")
        return judge_config_id

    async def get_judge_configs(self, workspace_id: str) -> Sequence[SQLAJudgeConfig]:
        """List judge configs in a workspace (excluding soft-deleted)."""
        async with self.db.session() as session:
            query = (
                select(SQLAJudgeConfig)
                .where(SQLAJudgeConfig.workspace_id == workspace_id)
                .where(SQLAJudgeConfig.deleted_at.is_(None))  # Filter out soft-deleted
                .order_by(SQLAJudgeConfig.created_at.desc())
            )
            result = await session.execute(query)
            return result.scalars().all()

    async def get_judge_config(self, judge_config_id: str) -> SQLAJudgeConfig | None:
        """Fetch a single judge config by ID if it has not been soft-deleted."""
        async with self.db.session() as session:
            query = (
                select(SQLAJudgeConfig)
                .where(SQLAJudgeConfig.id == judge_config_id)
                .where(SQLAJudgeConfig.deleted_at.is_(None))
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def delete_judge_config(self, judge_config_id: str) -> bool:
        """Soft delete a judge config by setting deleted_at timestamp."""
        async with self.db.session() as session:
            result = await session.execute(
                update(SQLAJudgeConfig)
                .where(SQLAJudgeConfig.id == judge_config_id)
                .where(SQLAJudgeConfig.deleted_at.is_(None))  # Only delete if not already deleted
                .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
            )
            await session.commit()
            return result.rowcount > 0

    #######################
    # OpenAI Compatible Backends #
    #######################

    async def create_openai_compatible_backend(
        self,
        workspace_id: str,
        name: str,
        provider: str,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        backend_id: str | None = None,
    ) -> str:
        """Create a new OpenAI-compatible backend config in a workspace."""
        backend_id = backend_id or str(uuid4())

        async with self.db.session() as session:
            session.add(
                SQLAOpenAICompatibleBackend(
                    id=backend_id,
                    name=name,
                    provider=provider,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    workspace_id=workspace_id,
                )
            )

        logger.info(
            f"Created OpenAICompatibleBackend with ID: {backend_id} in workspace: {workspace_id}"
        )
        return backend_id

    async def get_openai_compatible_backends(
        self, workspace_id: str
    ) -> Sequence[SQLAOpenAICompatibleBackend]:
        """List OpenAI-compatible backend configs in a workspace (excluding soft-deleted)."""
        async with self.db.session() as session:
            query = (
                select(SQLAOpenAICompatibleBackend)
                .where(SQLAOpenAICompatibleBackend.workspace_id == workspace_id)
                .where(SQLAOpenAICompatibleBackend.deleted_at.is_(None))  # Filter out soft-deleted
                .order_by(SQLAOpenAICompatibleBackend.created_at.desc())
            )
            result = await session.execute(query)
            return result.scalars().all()

    async def get_openai_compatible_backend(
        self, backend_id: str
    ) -> SQLAOpenAICompatibleBackend | None:
        """Fetch a single OpenAI-compatible backend if it has not been soft-deleted."""
        async with self.db.session() as session:
            query = (
                select(SQLAOpenAICompatibleBackend)
                .where(SQLAOpenAICompatibleBackend.id == backend_id)
                .where(SQLAOpenAICompatibleBackend.deleted_at.is_(None))
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def delete_openai_compatible_backend(self, backend_id: str) -> bool:
        """Soft delete an OpenAI-compatible backend config by setting deleted_at timestamp."""
        async with self.db.session() as session:
            result = await session.execute(
                update(SQLAOpenAICompatibleBackend)
                .where(SQLAOpenAICompatibleBackend.id == backend_id)
                .where(
                    SQLAOpenAICompatibleBackend.deleted_at.is_(None)
                )  # Only delete if not already deleted
                .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
            )
            await session.commit()
            return result.rowcount > 0

    #######################
    # Experiment Ideas    #
    #######################

    async def create_experiment_idea(
        self,
        workspace_id: str,
        name: str,
        idea: str,
        idea_id: str | None = None,
    ) -> str:
        """Create a new experiment idea in a workspace."""
        idea_id = idea_id or str(uuid4())

        async with self.db.session() as session:
            session.add(
                SQLAExperimentIdea(
                    id=idea_id,
                    name=name,
                    idea=idea,
                    workspace_id=workspace_id,
                )
            )

        logger.info(f"Created ExperimentIdea with ID: {idea_id} in workspace: {workspace_id}")
        return idea_id

    async def get_experiment_ideas(self, workspace_id: str) -> Sequence[SQLAExperimentIdea]:
        """List experiment ideas in a workspace (excluding soft-deleted)."""
        async with self.db.session() as session:
            query = (
                select(SQLAExperimentIdea)
                .where(SQLAExperimentIdea.workspace_id == workspace_id)
                .where(SQLAExperimentIdea.deleted_at.is_(None))  # Filter out soft-deleted
                .order_by(SQLAExperimentIdea.created_at.desc())
            )
            result = await session.execute(query)
            return result.scalars().all()

    async def get_experiment_idea(self, idea_id: str) -> SQLAExperimentIdea | None:
        """Fetch a single experiment idea by ID if it has not been soft-deleted."""
        async with self.db.session() as session:
            query = (
                select(SQLAExperimentIdea)
                .where(SQLAExperimentIdea.id == idea_id)
                .where(SQLAExperimentIdea.deleted_at.is_(None))
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def delete_experiment_idea(self, idea_id: str) -> bool:
        """Soft delete an experiment idea by setting deleted_at timestamp."""
        async with self.db.session() as session:
            result = await session.execute(
                update(SQLAExperimentIdea)
                .where(SQLAExperimentIdea.id == idea_id)
                .where(
                    SQLAExperimentIdea.deleted_at.is_(None)
                )  # Only delete if not already deleted
                .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
            )
            await session.commit()
            return result.rowcount > 0

    #######################
    # Base Interactions   #
    #######################

    async def create_base_context(
        self,
        workspace_id: str,
        name: str,
        prompt: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        interaction_id: str | None = None,
    ) -> str:
        """Create a new base interaction in a workspace."""
        interaction_id = interaction_id or str(uuid4())

        async with self.db.session() as session:
            base_context = SQLABaseContext(
                id=interaction_id,
                name=name,
                prompt=prompt,
                tools=tools,
                workspace_id=workspace_id,
            )
            session.add(base_context)
            await session.commit()
            logger.info(f"Created BaseContext with ID: {interaction_id}, tools: {tools}")

        logger.info(f"Created BaseContext with ID: {interaction_id} in workspace: {workspace_id}")
        return interaction_id

    async def get_base_contexts(self, workspace_id: str) -> Sequence[SQLABaseContext]:
        """List base interactions in a workspace (excluding soft-deleted)."""
        async with self.db.session() as session:
            query = (
                select(SQLABaseContext)
                .where(SQLABaseContext.workspace_id == workspace_id)
                .where(SQLABaseContext.deleted_at.is_(None))  # Filter out soft-deleted
                .order_by(SQLABaseContext.created_at.desc())
            )
            result = await session.execute(query)
            return result.scalars().all()

    async def get_base_context(self, interaction_id: str) -> SQLABaseContext | None:
        """Fetch a single base context by ID if it has not been soft-deleted."""
        async with self.db.session() as session:
            query = (
                select(SQLABaseContext)
                .where(SQLABaseContext.id == interaction_id)
                .where(SQLABaseContext.deleted_at.is_(None))
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def delete_base_context(self, interaction_id: str) -> bool:
        """Soft delete a base interaction by setting deleted_at timestamp."""
        async with self.db.session() as session:
            result = await session.execute(
                update(SQLABaseContext)
                .where(SQLABaseContext.id == interaction_id)
                .where(SQLABaseContext.deleted_at.is_(None))  # Only delete if not already deleted
                .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
            )
            await session.commit()
            return result.rowcount > 0

    #######################
    # Experiment Configs  #
    #######################

    async def create_counterfactual_experiment_config(
        self,
        workspace_id: str,
        judge_config_id: str,
        openai_compatible_backend_id: str,
        idea_id: str,
        base_context_id: str,
        num_counterfactuals: int = 1,
        num_replicas: int = 1,
        max_turns: int = 1,
        experiment_config_id: str | None = None,
    ) -> str:
        """
        Create a new experiment config in a workspace.

        Note: All referenced configs must belong to the same workspace.
        """
        experiment_config_id = experiment_config_id or str(uuid4())

        # TODO: Add validation to ensure all referenced entities belong to the same workspace

        async with self.db.session() as session:
            session.add(
                SQLACounterfactualExperimentConfig(
                    id=experiment_config_id,
                    workspace_id=workspace_id,
                    judge_config_id=judge_config_id,
                    openai_compatible_backend_id=openai_compatible_backend_id,
                    idea_id=idea_id,
                    base_context_id=base_context_id,
                    num_counterfactuals=num_counterfactuals,
                    num_replicas=num_replicas,
                    max_turns=max_turns,
                )
            )

        logger.info(
            f"Created ExperimentConfig with ID: {experiment_config_id} in workspace: {workspace_id}"
        )
        return experiment_config_id

    async def get_counterfactual_experiment_configs(
        self, workspace_id: str
    ) -> Sequence[SQLACounterfactualExperimentConfig]:
        """List experiment configs in a workspace."""
        async with self.db.session() as session:
            query = (
                select(SQLACounterfactualExperimentConfig)
                .where(SQLACounterfactualExperimentConfig.workspace_id == workspace_id)
                .where(
                    SQLACounterfactualExperimentConfig.deleted_at.is_(None)
                )  # Filter out deleted configs
                .order_by(SQLACounterfactualExperimentConfig.created_at.desc())
            )
            result = await session.execute(query)
            return result.scalars().all()

    async def get_counterfactual_experiment_config(
        self, experiment_config_id: str
    ) -> SQLACounterfactualExperimentConfig | None:
        """Get a single experiment config by ID."""
        async with self.db.session() as session:
            query = select(SQLACounterfactualExperimentConfig).where(
                SQLACounterfactualExperimentConfig.id == experiment_config_id
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def delete_counterfactual_experiment_config(self, experiment_config_id: str) -> bool:
        """Soft delete an experiment config."""

        async with self.db.session() as session:
            # Soft delete by setting deleted_at timestamp
            result = await session.execute(
                update(SQLACounterfactualExperimentConfig)
                .where(SQLACounterfactualExperimentConfig.id == experiment_config_id)
                .where(
                    SQLACounterfactualExperimentConfig.deleted_at.is_(None)
                )  # Only delete if not already deleted
                .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
            )
            await session.commit()
            deleted = result.rowcount > 0

            if deleted:
                logger.info(f"Soft deleted ExperimentConfig with ID: {experiment_config_id}")

            return deleted

    # Helper method to check if an experiment config exists
    async def experiment_config_exists(self, workspace_id: str, experiment_config_id: str) -> bool:
        """Check if an experiment config exists in a workspace (either type)."""
        counterfactual_configs = await self.get_counterfactual_experiment_configs(workspace_id)
        if any(c.id == experiment_config_id for c in counterfactual_configs):
            return True

        simple_rollout_configs = await self.get_simple_rollout_experiment_configs(workspace_id)
        if any(c.id == experiment_config_id for c in simple_rollout_configs):
            return True

        return False

    async def get_experiment_config_type(
        self, experiment_config_id: str
    ) -> Literal["counterfactual", "simple_rollout"] | None:
        """Get the type of an experiment config (counterfactual or simple_rollout)."""
        async with self.db.session() as session:
            # Check counterfactual experiments
            counterfactual = await session.get(
                SQLACounterfactualExperimentConfig, experiment_config_id
            )
            if counterfactual:
                return "counterfactual"

            # Check simple rollout experiments
            simple_rollout = await session.get(
                SQLASimpleRolloutExperimentConfig, experiment_config_id
            )
            if simple_rollout:
                return "simple_rollout"

            return None

    # SimpleRolloutExperiment methods
    async def create_simple_rollout_experiment_config(
        self,
        workspace_id: str,
        openai_compatible_backend_id: str,
        base_context_id: str,
        judge_config_id: str | None = None,
        num_replicas: int = 1,
        max_turns: int = 1,
        experiment_config_id: str | None = None,
    ) -> str:
        """
        Create a new simple rollout experiment config in a workspace.
        Note: Judge is optional for simple rollout experiments.
        """
        experiment_config_id = experiment_config_id or str(uuid4())

        async with self.db.session() as session:
            session.add(
                SQLASimpleRolloutExperimentConfig(
                    id=experiment_config_id,
                    workspace_id=workspace_id,
                    judge_config_id=judge_config_id,
                    openai_compatible_backend_id=openai_compatible_backend_id,
                    base_context_id=base_context_id,
                    num_replicas=num_replicas,
                    max_turns=max_turns,
                )
            )

        logger.info(
            f"Created SimpleRolloutExperimentConfig with ID: {experiment_config_id} in workspace: {workspace_id}"
        )
        return experiment_config_id

    async def get_simple_rollout_experiment_configs(
        self, workspace_id: str
    ) -> Sequence[SQLASimpleRolloutExperimentConfig]:
        """List simple rollout experiment configs in a workspace."""
        async with self.db.session() as session:
            query = (
                select(SQLASimpleRolloutExperimentConfig)
                .where(SQLASimpleRolloutExperimentConfig.workspace_id == workspace_id)
                .where(
                    SQLASimpleRolloutExperimentConfig.deleted_at.is_(None)
                )  # Filter out deleted configs
                .order_by(SQLASimpleRolloutExperimentConfig.created_at.desc())
            )
            result = await session.execute(query)
            return result.scalars().all()

    async def get_simple_rollout_experiment_config(
        self, experiment_config_id: str
    ) -> SQLASimpleRolloutExperimentConfig | None:
        """Get a single simple rollout experiment config by ID."""
        async with self.db.session() as session:
            query = select(SQLASimpleRolloutExperimentConfig).where(
                SQLASimpleRolloutExperimentConfig.id == experiment_config_id
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def delete_simple_rollout_experiment_config(self, experiment_config_id: str) -> bool:
        """Soft delete a simple rollout experiment config."""
        async with self.db.session() as session:
            # Soft delete by setting deleted_at timestamp
            result = await session.execute(
                update(SQLASimpleRolloutExperimentConfig)
                .where(SQLASimpleRolloutExperimentConfig.id == experiment_config_id)
                .where(
                    SQLASimpleRolloutExperimentConfig.deleted_at.is_(None)
                )  # Only delete if not already deleted
                .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
            )
            await session.commit()
            deleted = result.rowcount > 0

            if deleted:
                logger.info(
                    f"Soft deleted SimpleRolloutExperimentConfig with ID: {experiment_config_id}"
                )

            return deleted

    @asynccontextmanager
    async def advisory_lock(self, resource_id: str, action_id: str) -> AsyncIterator[None]:
        """Acquires a PostgreSQL advisory lock for the given resource ID and action ID.

        This provides a concurrency safety mechanism that can prevent race conditions
        when multiple processes or tasks attempt to modify the same resource.

        Args:
            resource_id: The resource ID to lock (e.g., workspace_id, experiment_config_id)
            action_id: An identifier for the action being performed

        Example:
            ```python
            async with investigator_svc.advisory_lock(experiment_config_id, "start_experiment"):
                # This code is protected by the lock
                await investigator_svc.start_experiment(experiment_config_id)
            ```
        """
        # Create integer keys from the string IDs using hash functions
        # We use two separate hashing algorithms to minimize collision risk
        resource_hash = int(hashlib.md5(resource_id.encode()).hexdigest(), 16) % (2**31 - 1)
        action_hash = int(hashlib.sha1(action_id.encode()).hexdigest(), 16) % (2**31 - 1)

        async with self.db.engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")

            try:
                # Acquire the advisory lock
                await conn.execute(
                    text("SELECT pg_advisory_lock(:key1, :key2)"),
                    {"key1": resource_hash, "key2": action_hash},
                )
                logger.info(f"Acquired advisory lock for {resource_id}/{action_id}")

                # Yield control back to the caller
                yield
            finally:
                # Always release the lock, even if an exception occurs
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:key1, :key2)"),
                    {"key1": resource_hash, "key2": action_hash},
                )
                logger.info(f"Released advisory lock for {resource_id}/{action_id}")

    async def is_user_authorized_for_investigator(self, user: User) -> bool:
        """Check if a user is authorized to access investigator features."""
        async with self.db.session() as session:
            from docent_core.investigator.db.schemas.experiment import (
                SQLATmpInvestigatorAuthorizedUser,
            )

            query = select(SQLATmpInvestigatorAuthorizedUser.user_id).where(
                SQLATmpInvestigatorAuthorizedUser.user_id == user.id
            )
            result = await session.execute(query)
            return result.scalar_one_or_none() is not None

    async def add_authorized_user(self, user_id: str) -> bool:
        """Add a user to the investigator authorized users list."""
        async with self.db.session() as session:
            from docent_core.investigator.db.schemas.experiment import (
                SQLATmpInvestigatorAuthorizedUser,
            )

            existing = await session.execute(
                select(SQLATmpInvestigatorAuthorizedUser).where(
                    SQLATmpInvestigatorAuthorizedUser.user_id == user_id
                )
            )
            if existing.scalar_one_or_none():
                return False  # User already authorized

            session.add(SQLATmpInvestigatorAuthorizedUser(user_id=user_id))
            await session.commit()
            return True

    async def remove_authorized_user(self, user_id: str) -> bool:
        """Remove a user from the investigator authorized users list."""
        async with self.db.session() as session:
            from docent_core.investigator.db.schemas.experiment import (
                SQLATmpInvestigatorAuthorizedUser,
            )

            result = await session.execute(
                delete(SQLATmpInvestigatorAuthorizedUser).where(
                    SQLATmpInvestigatorAuthorizedUser.user_id == user_id
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def get_all_authorized_users(self) -> list[dict[str, str | None]]:
        """Get all authorized investigator users with their details."""
        async with self.db.session() as session:
            from docent_core.docent.db.schemas.tables import TABLE_USER

            query = text(
                f"""
                SELECT
                    tmp_investigator_authorized_users.user_id,
                    tmp_investigator_authorized_users.created_at,
                    {TABLE_USER}.email
                FROM tmp_investigator_authorized_users
                JOIN {TABLE_USER} ON tmp_investigator_authorized_users.user_id = {TABLE_USER}.id
            """
            )

            result = await session.execute(query)
            rows = result.fetchall()

            return [
                {
                    "user_id": row.user_id,
                    "email": row.email,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    async def add_authorized_user_by_email(self, email: str) -> bool:
        """Add a user to the investigator authorized users list by email."""
        async with self.db.session() as session:
            from docent_core.docent.db.schemas.tables import TABLE_USER
            from docent_core.investigator.db.schemas.experiment import (
                SQLATmpInvestigatorAuthorizedUser,
            )

            user_query = text(f"SELECT id FROM {TABLE_USER} WHERE email = :email")
            user_result = await session.execute(user_query, {"email": email})
            user_id = user_result.scalar_one_or_none()

            if not user_id:
                return False  # User not found

            # Check if user is already authorized
            existing = await session.execute(
                select(SQLATmpInvestigatorAuthorizedUser).where(
                    SQLATmpInvestigatorAuthorizedUser.user_id == user_id
                )
            )
            if existing.scalar_one_or_none():
                return False  # User already authorized

            session.add(SQLATmpInvestigatorAuthorizedUser(user_id=user_id))
            await session.commit()
            return True
