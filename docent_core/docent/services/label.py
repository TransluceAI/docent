from typing import Any, AsyncContextManager, Callable, Optional
from uuid import uuid4

import jsonschema
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models.judge import Label
from docent_core.docent.db.schemas.label import (
    SQLALabel,
    SQLALabelSet,
)
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


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
        for label in labels:
            jsonschema.validate(label.label_value, label_set.label_schema_no_reqs)

        # Create the label
        sqla_labels = [SQLALabel.from_pydantic(label) for label in labels]
        self.session.add_all(sqla_labels)

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

    async def get_labels_in_label_sets(self, label_set_ids: list[str]) -> list[Label]:
        """Get all labels in multiple label sets.

        Args:
            label_set_ids: The label set IDs

        Returns:
            List of labels in the label sets
        """
        # Verify label sets exist
        for label_set_id in label_set_ids:
            label_set = await self.get_label_set(label_set_id)
            if label_set is None:
                raise ValueError(f"Label set {label_set_id} not found")

        result = await self.session.execute(
            select(SQLALabel).where(SQLALabel.label_set_id.in_(label_set_ids))
        )
        sqla_labels = result.scalars().all()
        return [sqla_label.to_pydantic() for sqla_label in sqla_labels]

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
        return True

    async def delete_label(self, label_id: str) -> None:
        """Delete a label.

        Args:
            label_id: The label ID
        """
        result = await self.session.execute(select(SQLALabel).where(SQLALabel.id == label_id))
        label_to_delete = result.scalar_one_or_none()
        if label_to_delete:
            await self.session.delete(label_to_delete)

    ##################
    # Label Set CRUD #
    ##################

    async def create_label_set(
        self, name: str, label_schema: dict[str, Any], description: Optional[str] = None
    ) -> str:
        """Create a label set with a JSON schema.

        Args:
            name: The label set name
            description: The label set description (optional)
            label_schema: JSON schema for validating labels

        Returns:
            The label set ID
        """
        label_set_id = str(uuid4())
        sqla_label_set = SQLALabelSet(
            id=label_set_id,
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

    async def get_all_label_sets(self) -> list[SQLALabelSet]:
        """Get all label sets.

        Returns:
            List of all label sets
        """
        result = await self.session.execute(select(SQLALabelSet))
        return list(result.scalars().all())

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
