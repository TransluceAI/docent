import traceback
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from docent._log_util import get_logger

logger = get_logger(__name__)

SINGLETONS = (int, float, str, bool)


class BaseMetadata(BaseModel):
    """Provides common functionality for accessing and validating metadata fields.
    All metadata classes should inherit from this class.

    Serialization Behavior:
        - Field descriptions are highly recommended and stored in serialized versions of the object.
        - When a subclass of BaseMetadata is uploaded to a server, all extra fields and their descriptions are retained.
        - To recover the original structure with proper typing upon download, use:
          `CustomMetadataClass.model_validate(obj.model_dump())`.

    Attributes:
        model_config: Pydantic configuration that allows extra fields.
        allow_fields_without_descriptions: Boolean indicating whether to allow fields without descriptions.
    """

    model_config = ConfigDict(extra="allow")
    allow_fields_without_descriptions: bool = False

    # Private attribute to store field descriptions
    _field_descriptions: dict[str, str | None] | None = PrivateAttr(default=None)
    _internal_basemetadata_fields: set[str] = PrivateAttr(
        default={
            "allow_fields_without_descriptions",
            "model_config",
            "_field_descriptions",
        }
    )

    @model_validator(mode="after")
    def _validate_field_types_and_descriptions(self):
        """Validates that all fields have descriptions and proper types.

        Returns:
            Self: The validated model instance.

        Raises:
            ValueError: If any field is missing a description or has an invalid type.
        """
        # Validate each field in the model
        for field_name, field_info in self.__class__.model_fields.items():
            if field_name in self._internal_basemetadata_fields:
                continue

            # Check that field has a description
            if field_info.description is None:
                if not self.allow_fields_without_descriptions:
                    raise ValueError(
                        f"Field `{field_name}` needs a description in the definition of `{self.__class__.__name__}`, like `{field_name}: T = Field(description=..., default=...)`. "
                        "To allow un-described fields, set `allow_fields_without_descriptions = True` on the instance or in your metadata class definition."
                    )

        # Validate that the metadata is JSON serializable
        try:
            self.model_dump_json()
        except Exception as e:
            raise ValueError(
                f"Metadata is not JSON serializable: {e}. Traceback: {traceback.format_exc()}"
            )

        return self

    def model_post_init(self, __context: Any) -> None:
        """Initializes field descriptions from extra data after model initialization.

        Args:
            __context: The context provided by Pydantic's post-initialization hook.
        """
        fd = self.model_extra.pop("_field_descriptions", None) if self.model_extra else None
        if fd is not None:
            self._field_descriptions = fd

    @model_serializer(mode="wrap")
    def _serialize_model(self, handler: SerializerFunctionWrapHandler):
        # Call the default serializer
        data = handler(self)

        # Dump the field descriptions
        if self._field_descriptions is None:
            self._field_descriptions = self._compute_field_descriptions()
        data["_field_descriptions"] = self._field_descriptions

        return data

    def model_dump(
        self, *args: Any, strip_internal_fields: bool = False, **kwargs: Any
    ) -> dict[str, Any]:
        data = super().model_dump(*args, **kwargs)

        # Remove internal fields if requested
        if strip_internal_fields:
            for field in self._internal_basemetadata_fields:
                if field in data:
                    data.pop(field)

        return data

    def get(self, key: str, default_value: Any = None) -> Any:
        """Gets a value from the metadata by key.

        Args:
            key: The key to look up in the metadata.
            default_value: Value to return if the key is not found. Defaults to None.

        Returns:
            Any: The value associated with the key, or the default value if not found.
        """
        # Check if the field exists in the model's fields
        if key in self.__class__.model_fields or (
            self.model_extra is not None and key in self.model_extra
        ):
            # Field exists, return its value (even if None)
            return getattr(self, key)

        logger.warning(f"Field '{key}' not found in {self.__class__.__name__}")
        return default_value

    def get_field_description(self, field_name: str) -> str | None:
        """Gets the description of a field defined in the model schema.

        Args:
            field_name: The name of the field.

        Returns:
            str or None: The description string if the field is defined in the model schema
                and has a description, otherwise None.
        """
        if self._field_descriptions is None:
            self._field_descriptions = self._compute_field_descriptions()

        if field_name in self._field_descriptions:
            return self._field_descriptions[field_name]

        logger.warning(
            f"Field description for '{field_name}' not found in {self.__class__.__name__}"
        )
        return None

    def get_all_field_descriptions(self) -> dict[str, str | None]:
        """Gets descriptions for all fields defined in the model schema.

        Returns:
            dict: A dictionary mapping field names to their descriptions.
                Only includes fields that have descriptions defined in the schema.
        """
        if self._field_descriptions is None:
            self._field_descriptions = self._compute_field_descriptions()
        return self._field_descriptions

    def _compute_field_descriptions(self) -> dict[str, str | None]:
        """Computes descriptions for all fields in the model.

        Returns:
            dict: A dictionary mapping field names to their descriptions.
        """
        field_descriptions: dict[str, Optional[str]] = {}
        for field_name, field_info in self.__class__.model_fields.items():
            if field_name not in self._internal_basemetadata_fields:
                field_descriptions[field_name] = field_info.description
        return field_descriptions


class BaseAgentRunMetadata(BaseMetadata):
    """Extends BaseMetadata with fields specific to agent evaluation runs.

    Attributes:
        scores: Dictionary of evaluation metrics.
        default_score_key: The primary evaluation metric key.
    """

    scores: dict[str, int | float | bool | None] = Field(
        description="A dict of score_key -> score_value. Use one key for each metric you're tracking."
    )
    default_score_key: str | None = Field(
        description="The default score key for the transcript; one top-line metric"
    )

    def get_default_score(self) -> int | float | bool | None:
        """Gets the default evaluation score.

        Returns:
            int, float, bool, or None: The value of the default score if a default score key is set,
                otherwise None.
        """
        if self.default_score_key is None:
            return None
        return self.scores.get(self.default_score_key)


class FrameDimension(BaseModel):
    """A dimension for organizing agent runs."""

    id: str
    name: str
    search_query: str | None = None
    metadata_key: str | None = None
    maintain_mece: bool | None = None
    loading_clusters: bool = False
    loading_bins: bool = False
    binIds: list[dict[str, Any]] | None = None
