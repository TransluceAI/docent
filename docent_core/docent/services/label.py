from datetime import UTC, datetime
from typing import Any, AsyncContextManager, Callable, Optional
from uuid import uuid4

import jsonschema
from jsonschema import ValidationError
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models import InlineCitation
from docent.data_models.judge import Label
from docent.judges.util.meta_schema import validate_judge_result_schema
from docent_core.docent.db.schemas.label import (
    Comment,
    SQLAComment,
    SQLALabel,
    SQLALabelSet,
    SQLATag,
)
from docent_core.docent.db.schemas.tables import SQLAUser
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


class BulkValidationError(Exception):
    """Raised when multiple labels fail validation."""

    def __init__(self, failures: list[tuple[str, ValidationError]]):
        self.failures = failures
        summary = f"Failed to validate {len(failures)} labels"
        details = "\n".join(f"Label {label_id}: {error.message}" for label_id, error in failures)
        super().__init__(f"{summary}:\n{details}")


class LabelSetWithCount(BaseModel):
    """Label set with count of labels."""

    id: str
    name: str
    description: str | None
    label_schema: dict[str, Any]
    label_count: int


class LabelService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        service: MonoService,
    ):
        """The `session_cm_factory` creates new sessions that commit writes immediately.
        This is helpful if you don't want to wait for results to be written."""

        self.session = session
        self.session_cm_factory = session_cm_factory
        self.service = service

    @staticmethod
    def _validate_tag_value(value: str) -> None:
        if len(value) > 255:
            raise ValueError("Tag value must be at most 255 characters long")

    async def _touch_label_set(self, label_set_id: str) -> None:
        """Update the label set's updated_at timestamp."""
        result = await self.session.execute(
            select(SQLALabelSet).where(SQLALabelSet.id == label_set_id)
        )
        label_set = result.scalar_one_or_none()
        if label_set:
            label_set.updated_at = datetime.now(UTC).replace(tzinfo=None)

    ################
    # Label CRUD #
    ################

    async def create_label(self, label: Label) -> None:
        """Create a label and validate against label set schema.

        Args:
            label: The label to create

        Raises:
            ValueError: If label set doesn't exist or validation fails
        """
        # Get the label set to validate against its schema
        label_set = await self.get_label_set(label.label_set_id)
        if label_set is None:
            raise ValueError(f"Label set {label.label_set_id} not found")

        # Validate label value against schema
        jsonschema.validate(label.label_value, label_set.label_schema_no_reqs)

        # Create the label
        sqla_label = SQLALabel.from_pydantic(label)
        self.session.add(sqla_label)

        # Update the label set's updated_at timestamp
        await self._touch_label_set(label.label_set_id)

    async def create_labels(self, labels: list[Label]) -> None:
        """Create multiple labels and validate against label set schema.

        Args:
            labels: The labels to create

        Raises:
            ValueError: If label set doesn't exist or validation fails
        """
        # Verify all labels are in the same label set
        label_set_ids = set([label.label_set_id for label in labels])
        if len(label_set_ids) != 1:
            raise ValueError("All labels must be in the same label set")
        label_set_id = label_set_ids.pop()

        # Get the label set to validate against its schema
        label_set = await self.get_label_set(label_set_id)
        if label_set is None:
            raise ValueError(f"Label set {label_set_id} not found")

        # Validate labels against schema
        failed: list[tuple[str, ValidationError]] = []
        for label in labels:
            try:
                jsonschema.validate(label.label_value, label_set.label_schema_no_reqs)
            except ValidationError as e:
                failed.append((label.id, e))

        if failed:
            raise BulkValidationError(failed)

        # Create the label
        sqla_labels = [SQLALabel.from_pydantic(label) for label in labels]
        self.session.add_all(sqla_labels)

        # Update the label set's updated_at timestamp
        await self._touch_label_set(label_set_id)

    async def get_label(self, label_id: str) -> Label | None:
        """Get a single label by ID.

        Args:
            label_id: The label ID

        Returns:
            The label or None if not found
        """
        result = await self.session.execute(select(SQLALabel).where(SQLALabel.id == label_id))
        sqla_label = result.scalar_one_or_none()
        if sqla_label is None:
            return None
        return sqla_label.to_pydantic()

    async def get_labels_by_label_set(
        self, label_set_id: str, filter_valid_labels: bool = False
    ) -> list[Label]:
        """Get all labels in a label set.

        Args:
            label_set_id: The label set ID

        Returns:
            List of labels in the label set
        """
        label_set = await self.get_label_set(label_set_id)
        if label_set is None:
            raise ValueError(f"Label set {label_set_id} not found")

        result = await self.session.execute(
            select(SQLALabel).where(SQLALabel.label_set_id == label_set_id)
        )
        sqla_labels = result.scalars().all()

        # Just return the labels if we're not filtering for valid labels
        if not filter_valid_labels:
            return [sqla_label.to_pydantic() for sqla_label in sqla_labels]

        # Else, only return valid labels. Labels are already validated on insertion,
        # but required fields aren't checked.
        valid_labels: list[Label] = []
        for sqla_label in sqla_labels:
            try:
                jsonschema.validate(sqla_label.label_value, label_set.label_schema)
                valid_labels.append(sqla_label.to_pydantic())
            except jsonschema.ValidationError:
                continue

        return valid_labels

    async def update_label(self, label_id: str, label_value: dict[str, Any]) -> bool:
        """Update a label's value and validate against schema.

        Args:
            label_id: The label ID
            label_value: The new label value

        Returns:
            True if updated successfully

        Raises:
            ValueError: If label doesn't exist or validation fails
        """
        # Get the existing label
        result = await self.session.execute(select(SQLALabel).where(SQLALabel.id == label_id))
        existing_label = result.scalar_one_or_none()
        if existing_label is None:
            raise ValueError(f"Label {label_id} not found")

        # Get the label set to validate against its schema
        label_set = await self.get_label_set(existing_label.label_set_id)
        if label_set is None:
            raise ValueError(f"Label set {existing_label.label_set_id} not found")

        # Validate new label value against schema
        jsonschema.validate(label_value, label_set.label_schema_no_reqs)

        # Update the label
        existing_label.label_value = label_value

        # Update the label set's updated_at timestamp
        await self._touch_label_set(existing_label.label_set_id)

        return True

    async def delete_label(self, label_id: str) -> None:
        """Delete a label.

        Args:
            label_id: The label ID
        """
        result = await self.session.execute(select(SQLALabel).where(SQLALabel.id == label_id))
        label_to_delete = result.scalar_one_or_none()
        if label_to_delete:
            label_set_id = label_to_delete.label_set_id
            await self.session.delete(label_to_delete)
            # Update the label set's updated_at timestamp
            await self._touch_label_set(label_set_id)

    async def delete_labels_by_label_set(self, label_set_id: str) -> None:
        """Delete all labels in a label set.

        Args:
            label_set_id: The label set ID
        """
        await self.session.execute(delete(SQLALabel).where(SQLALabel.label_set_id == label_set_id))
        # Update the label set's updated_at timestamp
        await self._touch_label_set(label_set_id)

    ##################
    # Label Set CRUD #
    ##################

    async def create_label_set(
        self,
        collection_id: str,
        name: str,
        label_schema: dict[str, Any],
        description: Optional[str] = None,
    ) -> str:
        """Create a label set with a JSON schema.

        Args:
            collection_id: The collection ID
            name: The label set name
            label_schema: JSON schema for validating labels
            description: The label set description (optional)

        Returns:
            The label set ID

        Raises:
            jsonschema.ValidationError: If the schema doesn't conform to the meta schema
            jsonschema.SchemaError: If the schema is not a valid JSON Schema 2020-12
        """
        # Validate that the label schema conforms to the meta schema
        logger.info(f"Validating label schema: {label_schema}")
        validate_judge_result_schema(label_schema)

        label_set_id = str(uuid4())
        sqla_label_set = SQLALabelSet(
            id=label_set_id,
            collection_id=collection_id,
            name=name,
            description=description,
            label_schema=label_schema,
        )
        self.session.add(sqla_label_set)
        return label_set_id

    async def get_label_set(self, label_set_id: str) -> SQLALabelSet | None:
        """Get a label set by ID.

        Args:
            label_set_id: The label set ID

        Returns:
            The label set or None if not found
        """
        result = await self.session.execute(
            select(SQLALabelSet).where(SQLALabelSet.id == label_set_id)
        )
        return result.scalar_one_or_none()

    async def get_all_label_sets(self, collection_id: str) -> list[SQLALabelSet]:
        """Get all label sets in a collection, ordered by most recently updated.

        Args:
            collection_id: The collection ID

        Returns:
            List of label sets in the collection, ordered by updated_at descending
        """
        result = await self.session.execute(
            select(SQLALabelSet)
            .where(SQLALabelSet.collection_id == collection_id)
            .order_by(SQLALabelSet.updated_at.desc())
        )
        return list(result.scalars().all())

    async def update_label_set(
        self,
        label_set_id: str,
        name: str,
        label_schema: dict[str, Any],
        description: Optional[str] = None,
    ) -> bool:
        """Update a label set.

        Args:
            label_set_id: The label set ID
            name: The new label set name
            label_schema: The new JSON schema for validating labels
            description: The new label set description (optional)

        Returns:
            True if updated successfully

        Raises:
            ValueError: If label set doesn't exist
            jsonschema.ValidationError: If the schema doesn't conform to the meta schema
            jsonschema.SchemaError: If the schema is not a valid JSON Schema 2020-12
        """
        # Validate that the label schema conforms to the meta schema
        validate_judge_result_schema(label_schema)

        result = await self.session.execute(
            select(SQLALabelSet).where(SQLALabelSet.id == label_set_id)
        )
        existing_label_set = result.scalar_one_or_none()
        if existing_label_set is None:
            raise ValueError(f"Label set {label_set_id} not found")

        # Update the label set fields
        existing_label_set.name = name
        existing_label_set.label_schema = label_schema
        existing_label_set.description = description
        existing_label_set.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return True

    async def delete_label_set(self, label_set_id: str) -> None:
        """Delete a label set (cascade deletes labels).

        Args:
            label_set_id: The label set ID
        """
        result = await self.session.execute(
            select(SQLALabelSet).where(SQLALabelSet.id == label_set_id)
        )
        label_set_to_delete = result.scalar_one_or_none()
        if label_set_to_delete:
            await self.session.delete(label_set_to_delete)

    async def get_label_sets_with_counts(self, collection_id: str) -> list[LabelSetWithCount]:
        """Get all label sets with label counts for a specific collection.

        Args:
            collection_id: The collection ID

        Returns:
            List of label sets with their label counts in this collection
        """
        # Get all label sets in this collection
        label_sets = await self.get_all_label_sets(collection_id)

        # Count labels for each label set
        result = await self.session.execute(
            select(SQLALabel.label_set_id, func.count(SQLALabel.id)).group_by(
                SQLALabel.label_set_id
            )
        )
        # Build a dict mapping label_set_id to count
        label_counts = {label_set_id: count for label_set_id, count in result.all()}

        # Combine label sets with their counts
        return [
            LabelSetWithCount(
                id=ls.id,
                name=ls.name,
                description=ls.description,
                label_schema=ls.label_schema,
                label_count=label_counts.get(ls.id, 0),
            )
            for ls in label_sets
        ]

    async def get_labels_by_agent_run(self, agent_run_id: str) -> list[Label]:
        """Get all labels for a specific agent run, ordered by label set's updated_at.

        Args:
            agent_run_id: The agent run ID

        Returns:
            List of labels for the agent run, ordered by label set's updated_at descending
        """
        result = await self.session.execute(
            select(SQLALabel)
            .join(SQLALabelSet, SQLALabel.label_set_id == SQLALabelSet.id)
            .where(SQLALabel.agent_run_id == agent_run_id)
            .order_by(SQLALabelSet.updated_at.desc())
        )
        sqla_labels = result.scalars().all()
        return [sqla_label.to_pydantic() for sqla_label in sqla_labels]

    async def get_label_sets_categorized_for_agent_run(
        self, collection_id: str, agent_run_id: str
    ) -> tuple[list[SQLALabelSet], list[SQLALabelSet]]:
        """Get label sets split by whether they have a label for this agent run.

        Returns:
            (available, filled) - available can accept new labels, filled already have one
        """
        all_label_sets = await self.get_all_label_sets(collection_id)

        result = await self.session.execute(
            select(SQLALabel.label_set_id).where(SQLALabel.agent_run_id == agent_run_id)
        )
        filled_ids = set(result.scalars().all())

        available = [ls for ls in all_label_sets if ls.id not in filled_ids]
        filled = [ls for ls in all_label_sets if ls.id in filled_ids]

        return available, filled

    ################
    # Comment CRUD #
    ################

    async def create_comment(
        self,
        user_id: str,
        collection_id: str,
        agent_run_id: str,
        citations: list[InlineCitation],
        content: str,
    ) -> None:
        sqla_comment = SQLAComment(
            id=str(uuid4()),
            user_id=user_id,
            collection_id=collection_id,
            agent_run_id=agent_run_id,
            citations=[citation.model_dump() for citation in citations],
            content=content,
        )
        self.session.add(sqla_comment)

    async def get_comment(self, comment_id: str) -> Comment | None:
        result = await self.session.execute(
            select(SQLAComment, SQLAUser.email)
            .join(SQLAUser, SQLAComment.user_id == SQLAUser.id)
            .where(SQLAComment.id == comment_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        sqla_comment, user_email = row
        return sqla_comment.to_pydantic(user_email=user_email)

    async def get_comments_by_agent_run(self, agent_run_id: str) -> list[Comment]:
        result = await self.session.execute(
            select(SQLAComment, SQLAUser.email)
            .join(SQLAUser, SQLAComment.user_id == SQLAUser.id)
            .where(SQLAComment.agent_run_id == agent_run_id)
        )
        return [
            sqla_comment.to_pydantic(user_email=user_email)
            for sqla_comment, user_email in result.all()
        ]

    async def get_comments_by_collection(self, collection_id: str) -> list[Comment]:
        result = await self.session.execute(
            select(SQLAComment, SQLAUser.email)
            .join(SQLAUser, SQLAComment.user_id == SQLAUser.id)
            .where(SQLAComment.collection_id == collection_id)
        )
        return [
            sqla_comment.to_pydantic(user_email=user_email)
            for sqla_comment, user_email in result.all()
        ]

    async def update_comment(self, comment_id: str, content: str) -> bool:
        """Update a comment's content.

        Args:
            comment_id: The comment ID
            content: The new comment content

        Returns:
            True if updated successfully

        Raises:
            ValueError: If comment doesn't exist
        """
        result = await self.session.execute(select(SQLAComment).where(SQLAComment.id == comment_id))
        existing_comment = result.scalar_one_or_none()
        if existing_comment is None:
            raise ValueError(f"Comment {comment_id} not found")

        existing_comment.content = content
        return True

    async def delete_comment(self, comment_id: str) -> None:
        result = await self.session.execute(select(SQLAComment).where(SQLAComment.id == comment_id))
        comment_to_delete = result.scalar_one_or_none()
        if comment_to_delete:
            await self.session.delete(comment_to_delete)

    #############
    # Tag CRUD  #
    #############

    class AgentRunCollectionMismatchError(ValueError):
        """Raised when an agent run is missing or belongs to another collection."""

    async def create_tag(self, collection_id: str, agent_run_id: str, value: str, created_by: str):
        """Create a tag for an agent run."""
        self._validate_tag_value(value)

        # Verify that the agent run belongs to the collection, raising an error if it doesn't.
        await self.service.check_agent_run_in_collection(collection_id, agent_run_id)

        sqla_tag = SQLATag(
            id=str(uuid4()),
            collection_id=collection_id,
            agent_run_id=agent_run_id,
            value=value,
            created_by=created_by,
        )
        self.session.add(sqla_tag)

        # Flush to surface FK violations and populate defaults like created_at
        await self.session.flush()
        await self.session.refresh(sqla_tag)

    async def delete_tag(self, tag_id: str) -> bool:
        """Delete a tag by ID."""
        result = await self.session.execute(select(SQLATag).where(SQLATag.id == tag_id))
        tag_to_delete = result.scalar_one_or_none()
        if tag_to_delete is None:
            return False

        await self.session.delete(tag_to_delete)
        return True

    async def get_tags_by_value(self, collection_id: str, value: str | None) -> list[SQLATag]:
        """Get tags in a collection, optionally filtered by value."""
        if value is not None:
            self._validate_tag_value(value)

        query = select(SQLATag).where(SQLATag.collection_id == collection_id)
        if value is not None:
            query = query.where(SQLATag.value == value)

        result = await self.session.execute(query.order_by(SQLATag.created_at.desc()))
        return list(result.scalars().all())

    async def get_tags_for_agent_run(self, collection_id: str, agent_run_id: str) -> list[SQLATag]:
        """Get all tags for a specific agent run in a collection."""

        result = await self.session.execute(
            select(SQLATag)
            .where(
                SQLATag.collection_id == collection_id,
                SQLATag.agent_run_id == agent_run_id,
            )
            .order_by(SQLATag.created_at.desc())
        )
        return list(result.scalars().all())
