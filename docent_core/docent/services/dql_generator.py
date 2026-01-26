from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Literal, Mapping, Sequence

from sqlglot import exp

from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent.data_models.chat.message import AssistantMessage, SystemMessage, UserMessage
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.dql import (
    DQLExecutionError,
    DQLParseError,
    DQLRegistry,
    DQLValidationError,
    JsonFieldInfo,
    build_default_registry,
    parse_dql_query,
)
from docent_core.docent.services.dql import DQLQueryResult, DQLService
from docent_core.docent.services.llms import PROVIDER_PREFERENCES, LLMService

if TYPE_CHECKING:
    from docent_core.docent.db.schemas.auth_models import User

logger = get_logger(__name__)

MAX_SCHEMA_COLUMNS = 60


@dataclass(frozen=True)
class DQLGeneratorMessage:
    """A message in the DQL generation conversation."""

    role: Literal["user", "assistant", "system"]
    content: str
    query: str | None = None


@dataclass(frozen=True)
class RubricSchemaInfo:
    """Schema information for a rubric's output structure."""

    id: str
    version: int
    name: str | None
    output_fields: list[str]


@dataclass(frozen=True)
class DQLGenerationOutcome:
    """Result of a DQL generation request."""

    query: str
    assistant_message: str
    execution_result: DQLQueryResult | None
    execution_error: str | None
    used_tables: list[str]


def _normalize_query(query: str) -> str:
    """Strip trailing semicolons and whitespace from a query."""
    cleaned = query.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1]
    return cleaned.strip()


def _clean_generated_query(text: str) -> str:
    """Clean up a model-generated query string while preserving formatting."""
    cleaned = _strip_ansi(text or "")
    # Normalize line endings to \n and remove trailing whitespace per line
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in cleaned.split("\n")]
    # Remove leading/trailing blank lines
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _registry_columns_hint(registry: DQLRegistry) -> str:
    """Build a hint string listing available columns per table."""
    hints: list[str] = []
    for table in registry.iter_tables():
        cols = [c for c in sorted(table.allowed_columns) if c.lower() != "collection_id"]
        if cols:
            hints.append(f"{table.name}: {', '.join(cols)}")
    return "\n".join(hints)


def _prettify_base_query(
    query: str | None, registry: DQLRegistry, collection_id: str
) -> str | None:
    """Return the query with minimal normalization (no reformatting).

    Pretty-printing is disabled to preserve the user's original formatting,
    which allows the LLM to create clean, minimal diffs when editing queries.
    """
    # Unused but kept for potential future use
    _ = registry
    _ = collection_id
    if not query:
        return None
    return _normalize_query(query)


def _schema_summary(registry: DQLRegistry, max_columns: int = MAX_SCHEMA_COLUMNS) -> str:
    """Build a human-readable schema summary for the system prompt."""
    lines: list[str] = ["Tables you can use:"]
    for table in sorted(registry.iter_tables(), key=lambda tbl: tbl.name):
        alias_hint = f" (aliases: {', '.join(sorted(table.aliases))})" if table.aliases else ""
        lines.append(f"- {table.name}{alias_hint}")

        allowed_columns = sorted(
            col for col in table.allowed_columns if col.lower() != "collection_id"
        )
        shown_columns = allowed_columns[:max_columns]
        hidden_count = len(allowed_columns) - len(shown_columns)
        column_line = f"  columns: {', '.join(shown_columns)}"
        if hidden_count > 0:
            column_line += f" (+{hidden_count} more)"
        lines.append(column_line)

        if table.column_aliases:
            alias_pairs = [
                f"{alias} -> {target}" for alias, target in sorted(table.column_aliases.items())
            ]
            lines.append(f"  column aliases: {', '.join(alias_pairs)}")

        if table.json_field_paths:
            lines.append(f"  json fields: {', '.join(sorted(table.json_field_paths))}")
    return "\n".join(lines)


def _build_rubric_schema_summary(rubrics: Sequence[RubricSchemaInfo]) -> str:
    """Build a summary of rubric output schemas for the system prompt."""
    if not rubrics:
        return ""
    lines = ["", "RUBRIC OUTPUT SCHEMAS (use output->>'field' to access):"]
    for rubric in rubrics:
        name = rubric.name[:40] + "..." if rubric.name and len(rubric.name) > 40 else rubric.name
        fields_str = ", ".join(rubric.output_fields) if rubric.output_fields else "(no fields)"
        lines.append(f"- {rubric.id} (v{rubric.version}): {fields_str}")
        if name:
            lines.append(f"  Description: {name}")
    return "\n".join(lines)


def _build_system_prompt(
    schema_summary: str,
    current_query: str | None,
    rubric_schemas: Sequence[RubricSchemaInfo] | None = None,
) -> str:
    """Build the system prompt for the DQL generator."""
    prompt_lines = [
        "You write Docent Query Language (DQL) SELECT statements.",
        "Only use the tables and columns from the schema below.",
        "DQL allows a single read-only SELECT. Cast text/JSON fields to numeric when aggregating.",
        "If the request is unclear, ask a concise clarifying question before proposing DQL.",
        "Qualify columns when multiple tables appear.",
        "",
        "IMPORTANT: Do NOT include collection_id in your queries. The backend automatically scopes "
        "all queries to the current collection - you never need to filter by collection_id.",
        "",
        "When the user asks for a specific row by name or other attribute (e.g., 'show me the run "
        "named foo'), first write a query to find that row's id, then use that id in subsequent "
        "queries. If you need to look something up, say so in your notes.",
        "",
        "PRESERVING FORMATTING:",
        "- When editing an existing query, preserve its whitespace and formatting style.",
        "- Only change the lines that need to be modified to fulfill the user's request.",
        "- Do NOT reformat or reorganize the query unless the user specifically asks for cleanup.",
        "- This creates clean, minimal diffs that are easy to review.",
        "",
        "RUBRIC & JUDGE RESULTS:",
        "- `rubrics` table defines evaluation criteria with composite PK (id, version).",
        "- `judge_results` stores evaluation outcomes. Join via agent_run_id and (rubric_id, rubric_version).",
        "- Always filter: result_type = 'DIRECT_RESULT' to exclude failed evaluations.",
        "- Results are in `output` JSONB column. Use the RUBRIC OUTPUT SCHEMAS below to see available fields.",
        "",
        "HANDLING MULTIPLE ROLLOUTS:",
        "- Rubrics may have multiple judge_results rows per agent_run (for reliability via repeated evaluation).",
        "- To get the consensus/mode value, use mode() WITHIN GROUP:",
        "  mode() WITHIN GROUP (ORDER BY jr.output->>'label') AS label",
        "- Example CTE pattern for getting modal results per rubric:",
        "  WITH rubric_abc123_modes AS (",
        "    SELECT",
        "      jr.agent_run_id,",
        "      mode() WITHIN GROUP (ORDER BY jr.output->>'label') AS label,",
        "      mode() WITHIN GROUP (ORDER BY jr.output->>'explanation') AS explanation",
        "    FROM judge_results jr",
        "    WHERE jr.rubric_id = 'abc123...' AND jr.rubric_version = 2",
        "      AND jr.result_type = 'DIRECT_RESULT'",
        "    GROUP BY jr.agent_run_id",
        "  )",
        "- For multiple rubrics, create separate CTEs and FULL OUTER JOIN on agent_run_id.",
        "",
        "RUBRIC VERSIONING:",
        "- When user doesn't specify version, use the latest. Query max version or ORDER BY version DESC LIMIT 1.",
        "",
        "LABELS (distinct from rubrics):",
        "- `labels` table stores manual/human labels, joined via agent_run_id and filtered by label_set_id.",
        "- `label_value` is JSONB with fields like label_value->>'label', label_value->>'explanation'.",
        "",
        "DYNAMIC SCHEMA - DO NOT ASSUME STRUCTURE:",
        "- metadata_json, rubric output, and label_value structures vary per collection/rubric/label_set.",
        "- Check the RUBRIC OUTPUT SCHEMAS section below for available output fields per rubric.",
        "- If the schema doesn't show the fields you need, write a query to inspect the data first, e.g.:",
        "  SELECT DISTINCT jsonb_object_keys(output) FROM judge_results WHERE rubric_id = '...' LIMIT 100",
        "  SELECT DISTINCT jsonb_object_keys(metadata_json) FROM agent_runs LIMIT 100",
        "- Tell the user in your notes if you need to discover schema before writing the final query.",
        "",
        "DATA NOTES:",
        "- agent_runs: metadata_json contains run-level metadata (not rubric scores). Access nested fields "
        "with metadata_json->>'field' or metadata_json->'nested'->>'field'.",
        "- tags: Use array_agg(t.value ORDER BY t.value) to collect tags for an agent_run.",
        "",
        "OUTPUT FORMAT:",
        'Respond with JSON: {"dql": "<query>", "notes": "<markdown notes>"} and nothing else.',
        "- Format the notes field as markdown. Use `backticks` for column/table names.",
        "- If showing example SQL in notes, use ```sql code blocks.",
        "- Present yourself as the DQL expert. Focus notes on helping the user understand the query.",
        "- If the user points out an error, acknowledge it and explain the fix.",
        "- IMPORTANT: Your notes go directly to the user. The user does not see system retry messages.",
        "  Do NOT reference 'previous queries', 'fixing errors', 'corrections', or 'the error'",
        "  unless the user explicitly mentioned an error. Write notes as if this is your first response.",
        "- Never mention PostgreSQL or Postgres. Refer only to DQL.",
        "",
        "Schema:",
        schema_summary,
    ]

    # Add rubric output schemas if available
    if rubric_schemas:
        prompt_lines.append(_build_rubric_schema_summary(rubric_schemas))
    if current_query:
        prompt_lines.extend(
            [
                "",
                "Current working query (edit it when the user asks for changes):",
                current_query,
            ]
        )
    return "\n".join(prompt_lines)


def _strip_code_fence(text: str) -> str:
    """Remove markdown code fences from text."""
    fenced = text.strip()
    if fenced.startswith("```"):
        fenced = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", fenced, flags=re.DOTALL)
    return fenced.strip()


ANSI_PATTERN = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return ANSI_PATTERN.sub("", text)


def _extract_json_payload(raw_text: str) -> dict[str, object] | None:
    """Extract a JSON object from model output, handling code fences."""
    cleaned = _strip_code_fence(raw_text)
    try:
        payload: object = json.loads(cleaned)
        if isinstance(payload, dict):
            return payload  # type: ignore[reportReturnType]
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        if isinstance(payload, dict):
            return payload  # type: ignore[reportReturnType]
    except Exception:
        return None
    return None


def _parse_model_output(raw_text: str) -> tuple[str, str]:
    """Parse model output to extract the DQL query and notes."""
    payload = _extract_json_payload(raw_text)
    if payload:
        query_value = payload.get("dql") or payload.get("query")
        note_value = payload.get("notes") or payload.get("reasoning") or ""
        if isinstance(query_value, str):
            return _normalize_query(query_value), str(note_value) if note_value else ""

    # Fallback: try to extract a SELECT statement directly
    match = re.search(r"(?is)select\b.+", raw_text.strip())
    if match:
        return _normalize_query(match.group(0)), ""

    raise ValueError("Model response did not include a DQL query.")


def _tables_from_expression(expression: exp.Expression) -> list[str]:
    """Extract table names referenced in a parsed expression."""
    names: set[str] = set()
    for table in expression.find_all(exp.Table):
        if table.name:
            names.add(str(table.name))
    return sorted(names)


def _strip_collection_filters(expression: exp.Expression) -> exp.Expression:
    """Remove predicates that reference collection_id to avoid redundant filters."""
    where_expr = expression.args.get("where")
    if where_expr is None:
        return expression

    def _has_collection_column(node: exp.Expression) -> bool:
        return any(
            col.name and col.name.lower() == "collection_id" for col in node.find_all(exp.Column)
        )

    if _has_collection_column(where_expr):
        expression = expression.copy()
        expression.set("where", None)
        return expression

    return expression


class DQLGeneratorService:
    """Service for generating DQL queries from natural language using LLMs."""

    def __init__(self, dql_svc: DQLService, llm_svc: LLMService):
        self.dql_svc = dql_svc
        self.llm_svc = llm_svc

    async def _propose_query(
        self,
        *,
        system_prompt: str,
        messages: list[UserMessage | AssistantMessage | SystemMessage],
        registry: DQLRegistry,
        collection_id: str,
        user: "User",
        model_options: list[ModelOption],
    ) -> tuple[str, list[str], DQLQueryResult | None, str | None, str | None]:
        """Call the LLM to propose a query and attempt to execute it."""
        outputs = await self.llm_svc.get_completions(
            inputs=[messages],
            model_options=model_options,
            max_new_tokens=10 * 1024,
            temperature=1.0,
            use_cache=True,
        )

        result = outputs[0]
        if result.did_error or result.first is None or not result.first.text:
            error_details: list[str] = []
            if result.did_error:
                error_details.append(f"errors={result.errors}")
            if result.first is None:
                error_details.append("no completions returned")
            elif not result.first.text:
                error_details.append("empty text in completion")
            logger.info("DQL generator empty model response: %s", ", ".join(error_details))
            return "", [], None, "Model response did not include a DQL query.", None

        raw_text = result.first.text
        try:
            logger.info("DQL generator raw model response (truncated): %s", raw_text[:2000])
        except Exception:
            pass

        try:
            proposed_query, assistant_note = _parse_model_output(raw_text)
        except Exception as exc:
            return "", [], None, f"Model response did not include a DQL query: {exc}", raw_text

        proposed_query = _clean_generated_query(proposed_query)
        assistant_note = _strip_ansi(assistant_note or "")

        execution_result: DQLQueryResult | None = None
        execution_error: str | None = None
        used_tables: list[str] = []

        try:
            parsed_expression = parse_dql_query(
                proposed_query,
                registry=registry,
                collection_id=collection_id,
            )
            parsed_expression = _strip_collection_filters(parsed_expression)
            used_tables = _tables_from_expression(parsed_expression)
            # Execute the query (security scoping is added internally by execute_query)
            # but return the original proposed_query to the user, not the formatted version
            execution_result = await self.dql_svc.execute_query(
                user=user,
                collection_id=collection_id,
                dql=proposed_query,
            )
        except (DQLParseError, DQLValidationError, DQLExecutionError, Exception) as exc:
            execution_error = str(exc)
            logger.info(
                "DQL auto-generator produced a query that failed to run: %s", execution_error
            )

        # Return the original proposed_query, not a reformatted version
        return proposed_query, used_tables, execution_result, execution_error, assistant_note

    async def _load_registry(
        self, collection_id: str, json_fields: Mapping[str, Iterable[JsonFieldInfo]] | None = None
    ) -> tuple[DQLRegistry, str]:
        """Load the DQL registry and build a schema summary."""
        registry = build_default_registry(collection_id=collection_id, json_fields=json_fields)
        summary = _schema_summary(registry)
        return registry, summary

    def _choose_base_query(
        self, request_query: str | None, messages: Sequence[DQLGeneratorMessage]
    ) -> str | None:
        """Determine the base query to use from the request or message history."""
        if request_query and request_query.strip():
            return _normalize_query(request_query)

        for message in reversed(messages):
            if message.query and message.query.strip():
                return _normalize_query(message.query)
        return None

    def _convert_messages(
        self, messages: Sequence[DQLGeneratorMessage]
    ) -> list[UserMessage | AssistantMessage | SystemMessage]:
        """Convert DQLGeneratorMessage list to LLM message types."""
        converted: list[UserMessage | AssistantMessage | SystemMessage] = []
        for message in messages:
            content = message.content
            if message.query:
                content = f"{content.rstrip()}\n\nDQL query:\n{message.query}"

            if message.role == "assistant":
                converted.append(AssistantMessage(content=content))
            elif message.role == "system":
                converted.append(SystemMessage(content=content))
            else:
                converted.append(UserMessage(content=content))
        return converted

    async def generate(
        self,
        *,
        ctx: ViewContext,
        messages: Sequence[DQLGeneratorMessage],
        current_query: str | None = None,
        model_override: ModelOption | None = None,
        json_fields: Mapping[str, Iterable[JsonFieldInfo]] | None = None,
        rubric_schemas: Sequence[RubricSchemaInfo] | None = None,
    ) -> DQLGenerationOutcome:
        """Generate a DQL query from the conversation history.

        Args:
            ctx: The view context with user and collection info.
            messages: The conversation history.
            current_query: Optional current query in the editor.
            model_override: Optional model to use instead of defaults.
            json_fields: Optional pre-loaded JSON field metadata.
            rubric_schemas: Optional rubric output schema information.

        Returns:
            A DQLGenerationOutcome with the generated query and execution results.
        """
        if ctx.user is None:
            raise ValueError("User context is required to generate DQL.")

        if len(messages) == 0:
            raise ValueError("At least one message is required to generate DQL.")

        registry, schema_summary = await self._load_registry(ctx.collection_id, json_fields)
        base_query = self._choose_base_query(current_query, messages)
        base_query_pretty = _prettify_base_query(base_query, registry, ctx.collection_id)
        system_prompt = _build_system_prompt(
            schema_summary, base_query_pretty or base_query, rubric_schemas
        )
        base_messages: list[UserMessage | AssistantMessage | SystemMessage] = [
            SystemMessage(content=system_prompt),
            *self._convert_messages(messages),
        ]

        model_options = [model_override] if model_override else PROVIDER_PREFERENCES.dql_generator

        allowed_hint = _registry_columns_hint(registry)

        final_query = ""
        execution_result: DQLQueryResult | None = None
        execution_error: str | None = None
        assistant_message: str | None = ""
        used_tables: list[str] = []

        # Retry loop: up to 3 attempts
        for attempt in range(3):
            (
                final_query,
                used_tables,
                execution_result,
                execution_error,
                assistant_note,
            ) = await self._propose_query(
                system_prompt=system_prompt,
                messages=base_messages,
                registry=registry,
                collection_id=ctx.collection_id,
                user=ctx.user,
                model_options=model_options,
            )

            if assistant_note:
                assistant_message = assistant_note

            if execution_result is not None or not execution_error:
                break

            # Build retry message with error context
            retry_user_message = UserMessage(
                content=(
                    "The previous query failed. Error:\n"
                    f"{execution_error}\n\n"
                    f"Previous query:\n{final_query or '<empty>'}\n\n"
                    "Use only columns from the schema. Avoid '*' and invalid columns. "
                    "Columns by table:\n"
                    f"{allowed_hint}\n\n"
                    'Return corrected DQL as JSON: {"dql": "...", "notes": "..."}.'
                )
            )
            base_messages = [
                SystemMessage(content=system_prompt),
                *self._convert_messages(messages),
                retry_user_message,
            ]
            logger.info(
                "DQL generator retry attempt %d with error: %s", attempt + 1, execution_error
            )

        return DQLGenerationOutcome(
            query=final_query,
            assistant_message=assistant_message or "",
            execution_result=execution_result,
            execution_error=execution_error,
            used_tables=used_tables,
        )
