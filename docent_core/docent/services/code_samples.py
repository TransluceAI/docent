from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Sequence

from docent._log_util import get_logger
from docent_core.docent.db.filters import (
    AgentRunIdFilter,
    CollectionFilter,
    ComplexFilter,
    PrimitiveFilter,
)

logger = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "code_samples_templates"


class PythonSampleType(str, Enum):
    AGENT_RUNS = "agent_runs"
    DQL = "dql"
    RUBRIC_RESULTS = "rubric_results"


class SampleFormat(str, Enum):
    PYTHON = "python"
    NOTEBOOK = "notebook"


@dataclass
class PythonSample:
    filename: str
    description: str
    dql_query: str
    content: str
    format: SampleFormat


class CodeSampleService:
    """Builds runnable code samples for DQL exports."""

    @staticmethod
    def build_agent_runs_sample(
        *,
        api_key: str,
        server_url: str,
        collection_id: str,
        columns: Sequence[str],
        sort_field: str | None,
        sort_direction: Literal["asc", "desc"],
        base_filter: ComplexFilter | None,
        limit: int | None,
        format: SampleFormat = SampleFormat.PYTHON,
    ) -> PythonSample:
        dql_query = CodeSampleService.build_agent_runs_dql_query(
            columns=columns,
            sort_field=sort_field,
            sort_direction=sort_direction,
            base_filter=base_filter,
            limit=limit,
        )
        description = "Fetches agent runs via DQL and loads them into pandas."
        filename = f"agent_runs_{collection_id}"
        return CodeSampleService.build_dql_sample(
            api_key=api_key,
            server_url=server_url,
            collection_id=collection_id,
            dql_query=dql_query,
            description=description,
            filename=filename,
            format=format,
        )

    @staticmethod
    def build_dql_sample(
        *,
        api_key: str,
        server_url: str,
        collection_id: str,
        dql_query: str,
        description: str,
        filename: str,
        format: SampleFormat = SampleFormat.PYTHON,
    ) -> PythonSample:
        sanitized_query = CodeSampleService._sanitize_dql_query(dql_query)
        if format == SampleFormat.NOTEBOOK:
            content = CodeSampleService._build_notebook_content(
                api_key=api_key,
                server_url=server_url,
                collection_id=collection_id,
                dql_query=sanitized_query,
                description=description,
            )
            filename = filename if filename.endswith(".ipynb") else f"{filename}.ipynb"
        else:
            context = {
                "DESCRIPTION": description,
                "API_KEY": CodeSampleService._escape_double_quotes(api_key),
                "SERVER_URL": CodeSampleService._escape_double_quotes(server_url),
                "COLLECTION_ID": CodeSampleService._escape_double_quotes(collection_id),
                "DQL_QUERY": sanitized_query,
            }
            content = CodeSampleService._render_template("dql_sample.py", context)
            filename = filename if filename.endswith(".py") else f"{filename}.py"

        return PythonSample(
            filename=filename,
            description=description,
            dql_query=sanitized_query,
            content=content,
            format=format,
        )

    @staticmethod
    def build_rubric_results_sample(
        *,
        api_key: str,
        server_url: str,
        collection_id: str,
        rubric_id: str,
        rubric_version: int | None,
        runs_filter: ComplexFilter | None,
        limit: int | None,
        format: SampleFormat = SampleFormat.PYTHON,
    ) -> PythonSample:
        dql_query = CodeSampleService.build_rubric_results_dql_query(
            rubric_id=rubric_id,
            rubric_version=rubric_version,
            runs_filter=runs_filter,
            limit=limit,
        )
        description = "Pulls rubric results and run metadata into pandas via the Docent SDK."
        filename = f"rubric_{rubric_id}_results"
        return CodeSampleService.build_dql_sample(
            api_key=api_key,
            server_url=server_url,
            collection_id=collection_id,
            dql_query=dql_query,
            description=description,
            filename=filename,
            format=format,
        )

    @staticmethod
    def build_agent_runs_dql_query(
        *,
        columns: Sequence[str],
        sort_field: str | None,
        sort_direction: Literal["asc", "desc"],
        base_filter: ComplexFilter | None,
        limit: int | None,
        table_alias: str = "ar",
    ) -> str:
        unique_columns: list[str] = []
        for col in ["agent_run_id", *columns]:
            if col not in unique_columns:
                unique_columns.append(col)

        select_lines = [
            CodeSampleService._build_select_expression(column, table_alias)
            for column in unique_columns
        ]

        sort_expr = None
        if sort_field == "agent_run_id":
            sort_expr = f"{table_alias}.id"
        elif sort_field:
            sort_expr = CodeSampleService._build_field_expression(
                sort_field.split("."), table_alias
            )
        if not sort_expr:
            sort_expr = f"{table_alias}.created_at"

        where_clause = CodeSampleService.build_where_clause(base_filter, table_alias)

        lines = [
            "SELECT",
            ",\n".join(f"  {line}" for line in select_lines),
            f"FROM agent_runs {table_alias}",
            where_clause,
            f"ORDER BY {sort_expr} {'ASC' if sort_direction == 'asc' else 'DESC'}",
        ]
        if limit is not None:
            normalized_limit = max(1, int(limit))
            lines.append(f"LIMIT {normalized_limit};")

        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def build_rubric_results_dql_query(
        *,
        rubric_id: str,
        rubric_version: int | None,
        runs_filter: ComplexFilter | None,
        limit: int | None,
    ) -> str:
        where_clauses = [
            f"jr.rubric_id = '{CodeSampleService._escape_literal(rubric_id)}'",
        ]
        if rubric_version is not None:
            where_clauses.append(f"jr.rubric_version = {rubric_version}")

        run_filter_condition = (
            CodeSampleService._build_collection_filter_clause(runs_filter, "ar")
            if runs_filter
            else None
        )
        if run_filter_condition:
            where_clauses.append(f"({run_filter_condition})")

        where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        lines = [
            "SELECT",
            "  jr.id AS judge_result_id",
            "  , jr.agent_run_id",
            "  , jr.rubric_version",
            "  , jr.result_type",
            "  , jr.output",
            "  , jr.result_metadata",
            "  , ar.created_at AS run_created_at",
            "  , ar.metadata_json AS run_metadata",
            "FROM judge_results jr",
            "JOIN agent_runs ar ON ar.id = jr.agent_run_id",
            where_clause,
            "ORDER BY ar.created_at DESC",
        ]
        if limit is not None:
            normalized_limit = max(1, int(limit))
            lines.append(f"LIMIT {normalized_limit};")

        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def build_where_clause(filter_obj: ComplexFilter | None, table_alias: str) -> str:
        if not filter_obj:
            return ""
        condition = CodeSampleService._build_collection_filter_clause(filter_obj, table_alias)
        return f"WHERE {condition}" if condition else ""

    @staticmethod
    def _load_template(name: str) -> str:
        template_path = TEMPLATE_DIR / name
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        return template_path.read_text(encoding="utf-8")

    @staticmethod
    def _render_template(template_name: str, context: dict[str, str]) -> str:
        template = CodeSampleService._load_template(template_name)
        content = template
        for key, value in context.items():
            content = content.replace(f"{{{{{key}}}}}", value)
        return content

    @staticmethod
    def _build_notebook_content(
        *,
        api_key: str,
        server_url: str,
        collection_id: str,
        dql_query: str,
        description: str,
    ) -> str:
        context = {
            "DESCRIPTION": CodeSampleService._escape_json_string(description),
            "API_KEY": CodeSampleService._escape_json_string(api_key),
            "SERVER_URL": CodeSampleService._escape_json_string(server_url),
            "COLLECTION_ID": CodeSampleService._escape_json_string(collection_id),
            "DQL_QUERY": CodeSampleService._escape_json_string(dql_query),
        }
        return CodeSampleService._render_template("dql_sample.ipynb", context)

    @staticmethod
    def _escape_literal(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def _escape_double_quotes(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _escape_json_string(value: str) -> str:
        # json.dumps returns a quoted string; strip the surrounding quotes to embed safely.
        return json.dumps(value)[1:-1]

    @staticmethod
    def _sanitize_dql_query(query: str) -> str:
        return query.replace('"""', '\\"""').strip()

    @staticmethod
    def _build_metadata_accessor(
        path: Sequence[str],
        table_alias: str,
        comparison_value: object | None = None,
    ) -> str:
        if not path:
            raise ValueError("Metadata path cannot be empty")

        accessor = f"{table_alias}.metadata_json"
        for segment in path[:-1]:
            accessor = f"{accessor}->'{CodeSampleService._escape_literal(segment)}'"

        last_segment = CodeSampleService._escape_literal(path[-1])
        accessor = f"{accessor}->>'{last_segment}'"

        if isinstance(comparison_value, (int, float)):
            return f"CAST({accessor} AS DOUBLE PRECISION)"
        if isinstance(comparison_value, bool):
            return f"CAST({accessor} AS BOOLEAN)"
        return accessor

    @staticmethod
    def _build_field_expression(
        key_path: Sequence[str], table_alias: str, comparison_value: object | None = None
    ) -> str | None:
        if not key_path:
            return None

        root, *rest = key_path
        if root == "metadata" and rest:
            return CodeSampleService._build_metadata_accessor(rest, table_alias, comparison_value)
        if root == "agent_run_id":
            return f"{table_alias}.id"
        if root == "created_at":
            return f"{table_alias}.created_at"
        return f"{table_alias}.{root}"

    @staticmethod
    def _format_value(value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        return f"'{CodeSampleService._escape_literal(str(value))}'"

    @staticmethod
    def _build_primitive_clause(filter_obj: PrimitiveFilter, table_alias: str) -> str | None:
        if filter_obj.disabled or filter_obj.supports_sql is False:
            return None

        field_expr = CodeSampleService._build_field_expression(
            filter_obj.key_path, table_alias, filter_obj.value
        )
        if not field_expr:
            return None

        op = str(filter_obj.op)
        if op == "is":
            normalized = (
                filter_obj.value.strip().lower() if isinstance(filter_obj.value, str) else None
            )
            if normalized == "null":
                return f"{field_expr} IS NULL"
            if normalized == "not null":
                return f"{field_expr} IS NOT NULL"
            return f"{field_expr} IS {CodeSampleService._format_value(filter_obj.value)}"

        formatted_value = CodeSampleService._format_value(filter_obj.value)
        if op in {"==", "!=", ">", ">=", "<", "<=", "~*", "!~*"}:
            sql_op = "=" if op == "==" else op
            return f"{field_expr} {sql_op} {formatted_value}"

        return None

    @staticmethod
    def _build_agent_run_id_clause(filter_obj: AgentRunIdFilter, table_alias: str) -> str | None:
        if filter_obj.disabled or filter_obj.supports_sql is False:
            return None
        if not filter_obj.agent_run_ids:
            return None
        values = ", ".join(
            f"'{CodeSampleService._escape_literal(agent_run_id)}'"
            for agent_run_id in filter_obj.agent_run_ids
        )
        return f"{table_alias}.id IN ({values})"

    @staticmethod
    def _build_collection_filter_clause(
        filter_obj: CollectionFilter, table_alias: str
    ) -> str | None:
        if (
            getattr(filter_obj, "disabled", False)
            or getattr(filter_obj, "supports_sql", True) is False
        ):
            return None

        if isinstance(filter_obj, PrimitiveFilter):
            return CodeSampleService._build_primitive_clause(filter_obj, table_alias)
        if isinstance(filter_obj, AgentRunIdFilter):
            return CodeSampleService._build_agent_run_id_clause(filter_obj, table_alias)

        # Remaining supported type is ComplexFilter
        inner = [
            clause
            for clause in (
                CodeSampleService._build_collection_filter_clause(child, table_alias)
                for child in getattr(filter_obj, "filters", [])
            )
            if clause
        ]
        if not inner:
            return None
        joiner = " OR " if getattr(filter_obj, "op", "and") == "or" else " AND "
        return f"({joiner.join(inner)})"

    @staticmethod
    def _build_select_expression(column: str, table_alias: str) -> str:
        if column == "agent_run_id":
            return f"{table_alias}.id AS agent_run_id"
        if column.startswith("metadata."):
            path = column.split(".")[1:]
            expr = CodeSampleService._build_metadata_accessor(path, table_alias)
            alias = column.replace(".", "_")
            return f"{expr} AS {alias}"
        return f"{table_alias}.{column} AS {column}"
