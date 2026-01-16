import enum
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from docent._llm_util.providers.preference_types import PUBLIC_PROVIDER_PREFERENCES, ModelOption
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    UserMessage,
)
from docent.data_models.transcript import TEXT_RANGE_CITE_INSTRUCTION
from docent.judges.util.meta_schema import validate_judge_result_schema
from docent.judges.util.template_formatter import AgentRunTemplateFormatter
from docent.sdk.llm_context import LLMContext, resolve_citations_with_context

logger = get_logger(__name__)

############
# Defaults #
############

# Prompt templates for various "default" judges
DEFAULT_JUDGE_SYSTEM_PROMPT_TEMPLATE = """
Here is a rubric that we are using to judge transcripts of AI agent runs.

Rubric:
<rubric>
{rubric}
</rubric>

Agent run:
<agent_run>
{agent_run}
</agent_run>

Your goal is to judge the agent run according to the criteria given in the rubric. Start by faithfully following the decision procedure in extremely careful detail, step by step.

When you are finished, output your final adjudication, surrounded by <response>...</response> tags. The response must be a valid JSON string which can be parsed with python `json.loads` without any additional processing. Double quotes (`"`) in the middle of a string in the JSON object must be escaped with a backslash.

The JSON object you produce must adhere to the following schema:
{output_schema}
""".strip()

DEFAULT_MULTI_TURN_JUDGE_SYSTEM_PROMPT_TEMPLATE = """
Here is a rubric that we are using to judge transcripts of AI agent runs.

Rubric:
<rubric>
{rubric}
</rubric>

Agent run:
<agent_run>
{agent_run}
</agent_run>

Your goal is to judge the agent run according to the criteria given in the rubric. Start by faithfully following the decision procedure in extremely careful detail, step by step. You must execute **one step in the decision procedure per assistant message turn**. After each turn, output a complete and detailed recount of all actions you took, and everything you discovered. Then call the `step_finished` tool.

When you are finished going through the decision procedure, output your final adjudication, surrounded by <response>...</response> tags. The response must be a valid JSON string which can be parsed with python `json.loads` without any additional processing. Double quotes (`"`) in the middle of a string in the JSON object must be escaped with a backslash.

The JSON object you produce must adhere to the following schema:
{output_schema}
""".strip()

DEFAULT_EXPOSED_REASONING_JUDGE_SYSTEM_PROMPT_TEMPLATE = """
Here is a rubric that we are using to judge transcripts of AI agent runs.

Rubric:
<rubric>
{rubric}
</rubric>

Agent run:
<agent_run>
{agent_run}
</agent_run>

Your goal is to judge the agent run according to the criteria given in the rubric. Start by faithfully following the decision procedure in extremely careful detail, step by step. You must *fully externalize* your reasoning work by outputting details in the assistant message, surrounded by <reasoning>...</reasoning> tags. The reasoning section can be as messy as you need. You should use *high* reasoning effort.

When you are finished, output your final adjudication in the assistant message, surrounded by <response>...</response> tags. The response must be a valid JSON string which can be parsed with python `json.loads` without any additional processing. Double quotes (`"`) in the middle of a string in the JSON object must be escaped with a backslash.

The JSON object you produce must adhere to the following schema:
{output_schema}
""".strip()

# Other judge defaults
DEFAULT_JUDGE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["match", "no match"]},
        "explanation": {"type": "string", "citations": True},
    },
    # Require these properties to be present
    "required": ["label", "explanation"],
    # Allow additional properties though, as their presence is not breaking
}
DEFAULT_JUDGE_MODEL = PUBLIC_PROVIDER_PREFERENCES.default_judge_models[0]

# Citation instructions
JUDGE_CITATION_INSTRUCTIONS = f"""
For strings which require citations (according to the `citations: True` property), you must also follow these instructions:
{TEXT_RANGE_CITE_INSTRUCTION}
""".strip()


class JudgeVariant(str, enum.Enum):
    MAJORITY = "majority"
    MULTI_REFLECT = "multi-reflect"


class OutputParsingMode(str, enum.Enum):
    """Defines how LLM output is parsed to extract the JSON response."""

    CONSTRAINED_DECODING = (
        "constrained_decoding"  # Parse entire output as JSON (assumes constrained decoding)
    )
    XML_KEY = "xml_key"  # Extract content from within XML tags


class PromptTemplateMessage(BaseModel):
    """A single message in a prompt template for flexible judge configuration."""

    role: Literal["system", "user", "assistant"]
    content: str


class Rubric(BaseModel):
    """TODO(mengk): this should really be called JudgeConfig,
    but temporarily keeping this for consistency with docent_core."""

    class Config:
        frozen = True

    # Primary key
    id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = 1

    # What the judge actually does
    n_rollouts_per_input: int = 1
    judge_variant: JudgeVariant = JudgeVariant.MAJORITY
    rollout_type: Literal["single_turn"] = "single_turn"  # TODO(mengk): add to DB

    # Prompt templates
    prompt_templates: list[PromptTemplateMessage] = Field(
        default_factory=lambda: [
            PromptTemplateMessage(role="user", content=DEFAULT_JUDGE_SYSTEM_PROMPT_TEMPLATE)
        ]
    )

    # Auto-optimizable parameters
    rubric_text: str
    output_schema: dict[str, Any] = DEFAULT_JUDGE_OUTPUT_SCHEMA

    # LLM config
    judge_model: ModelOption = DEFAULT_JUDGE_MODEL

    # Output parsing
    output_parsing_mode: OutputParsingMode = OutputParsingMode.XML_KEY
    response_xml_key: str = "response"  # Only used when mode is XML_KEY

    def materialize_messages(self, agent_run: AgentRun) -> list[ChatMessage]:
        """Construct the message list for rubric evaluation.

        Uses the prompt_templates system.

        Args:
            agent_run: The agent run being judged

        Returns:
            A list of ChatMessage objects ready for LLM completion
        """
        citation_instructions = (
            JUDGE_CITATION_INSTRUCTIONS if _schema_requests_citations(self.output_schema) else ""
        )
        formatter = AgentRunTemplateFormatter(
            agent_run=agent_run,
            rubric_text=self.rubric_text,
            output_schema=self.output_schema,
        )

        # Format each template message
        messages: list[ChatMessage] = []
        for i, template in enumerate(self.prompt_templates):
            # No need to strip citation instructions here, as this is a new codepath
            content = formatter.format_template(template.content)

            # Auto-append citation instructions to the last message
            if i == len(self.prompt_templates) - 1 and citation_instructions:
                content = f"{content}\n\n{citation_instructions}"

            if template.role == "system":
                messages.append(SystemMessage(content=content))
            elif template.role == "user":
                messages.append(UserMessage(content=content))
            elif template.role == "assistant":
                messages.append(AssistantMessage(content=content))

        return messages

    @field_validator("prompt_templates")
    @classmethod
    def validate_prompt_templates(
        cls, prompt_templates: list[PromptTemplateMessage]
    ) -> list[PromptTemplateMessage]:
        if not prompt_templates:
            raise ValueError("prompt_templates must include at least one template message.")
        AgentRunTemplateFormatter.validate_template_variables([t.content for t in prompt_templates])
        return prompt_templates

    @field_validator("output_schema")
    @classmethod
    def validate_output_schema(cls, output_schema: dict[str, Any]):
        """
        Raises:
            jsonschema.ValidationError: If the schema is invalid
            jsonschema.SchemaError: If the schema is not a valid 2020-12 schema
        """
        validate_judge_result_schema(output_schema)
        return output_schema

    @model_validator(mode="after")
    def validate_output_parsing_mode_configuration(self) -> "Rubric":
        """Validate output parsing mode configuration.

        Rules:
        - When mode is XML_KEY, at least one template must mention the XML key
        """
        if self.output_parsing_mode == OutputParsingMode.XML_KEY:
            # Validate that the XML key is mentioned in at least one template
            # Only check the templates that will actually be used at runtime
            xml_tag = f"<{self.response_xml_key}>"
            templates_to_check = [t.content for t in self.prompt_templates]
            if not any(xml_tag in template for template in templates_to_check):
                raise ValueError(
                    f"When output_parsing_mode is XML_KEY, at least one template must contain "
                    f"the XML tag '<{self.response_xml_key}>'. "
                    f"Either add '{xml_tag}' to your templates or change the response_xml_key."
                )

        return self


class ExposedReasoningRubric(Rubric):
    prompt_templates: list[PromptTemplateMessage] = Field(
        default_factory=lambda: [
            PromptTemplateMessage(
                role="user",
                content=DEFAULT_EXPOSED_REASONING_JUDGE_SYSTEM_PROMPT_TEMPLATE,
            )
        ]
    )


class ResultType(enum.Enum):
    """Enum for the type of result that a judge result can have."""

    DIRECT_RESULT = "DIRECT_RESULT"
    FAILURE = "FAILURE"

    # Deprecated; do not use. Keeping for DB backward compatibility.
    NEAR_MISS = "NEAR_MISS"


class JudgeResult(BaseModel):
    class Config:
        frozen = True

    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    rubric_id: str
    rubric_version: int

    # Outputs
    output: dict[str, Any]
    result_metadata: dict[str, Any] | None = None
    result_type: ResultType

    # Deprecated
    value: str | None = None

    @field_serializer("result_type")
    def serialize_result_type(self, result_type: ResultType) -> str:
        return result_type.value


class JudgeResultWithCitations(JudgeResult):
    @classmethod
    def from_judge_result(
        cls, result: JudgeResult, schema: dict[str, Any], agent_run: AgentRun
    ) -> "JudgeResultWithCitations":
        """Judge result must be validated against the schema before calling this function!

        Args:
            result: The judge result to convert
            schema: The output schema used to validate the result
            agent_run: The agent run being judged (used to resolve citation aliases)
        """
        # LLMContext uses AgentRun.get_transcript_ids_ordered to sort transcripts within a run
        # So in the case of a single agent run, its numbering should match with Rubric.materialize_system_prompt
        context = LLMContext(items=[agent_run])

        def _parse_citation_string(output: str) -> dict[str, Any]:
            text, citations = resolve_citations_with_context(output, context)
            return {"text": text, "citations": [c.model_dump() for c in citations]}

        data = result.model_dump()
        try:
            data["output"] = traverse_schema_and_transform(
                data["output"], schema, _parse_citation_string
            )
        except Exception as e:
            logger.error(f"Failed to parse citations: {e}")
            logger.error(f"Output: {data['output']}")
            data["output"] = {"raw": data["output"]}
        return cls(**data)


class JudgeResultCompletionCallback(Protocol):
    """Called when some batch of judge results is completed.
    Supports batched calls for cases where many results are pre-computed.
    This avoids invoking the callback separately for each datapoint.
    """

    async def __call__(
        self,
        batch_index: int,
        judge_results: list[JudgeResult] | None,
    ) -> None: ...


def traverse_schema_and_transform(
    output: Any,
    schema: dict[str, Any],
    citation_string_handler: Callable[[str], Any],
) -> Any:
    """Recursively traverse output based on schema, applying citation_string_handler to citation strings."""
    if schema.get("type") == "string" and schema.get("citations"):  # type: ignore
        return citation_string_handler(output)
    elif schema.get("type") == "object":
        properties: dict[str, Any] = schema.get("properties", {})
        result: dict[str, Any] = {}
        for key in properties:
            if key in output:
                result[key] = traverse_schema_and_transform(
                    output[key], properties[key], citation_string_handler
                )
        return result
    elif schema.get("type") == "array":
        item_schema: dict[str, Any] = schema.get("items", {})
        return [
            traverse_schema_and_transform(item, item_schema, citation_string_handler)
            for item in output
        ]
    else:
        return output


def _schema_requests_citations(schema: dict[str, Any]) -> bool:
    """Check if any field in the schema requests citations by having 'citations': 'true'."""

    def _check_field(field_schema: Any) -> bool:
        if isinstance(field_schema, dict):
            if field_schema.get("citations"):  # type: ignore
                return True
            for value in field_schema.values():  # type: ignore
                if isinstance(value, dict) and _check_field(value):
                    return True
                elif isinstance(value, list):
                    for item in value:  # type: ignore
                        if isinstance(item, dict) and _check_field(item):
                            return True
        return False

    return _check_field(schema)
