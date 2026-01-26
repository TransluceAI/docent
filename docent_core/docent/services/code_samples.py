from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast

from docent._log_util import get_logger
from docent.judges import ResultType
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
        rubric_versions: Mapping[str, int] | None = None,
        format: SampleFormat = SampleFormat.PYTHON,
    ) -> PythonSample:
        dql_query = CodeSampleService.build_agent_runs_dql_query(
            columns=columns,
            sort_field=sort_field,
            sort_direction=sort_direction,
            base_filter=base_filter,
            limit=limit,
            rubric_versions=rubric_versions,
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
        rubric_version: int,
        output_schema: Mapping[str, Any] | None,
        runs_filter: ComplexFilter | None,
        limit: int | None,
        format: SampleFormat = SampleFormat.PYTHON,
    ) -> PythonSample:
        dql_query = CodeSampleService.build_rubric_results_dql_query(
            rubric_id=rubric_id,
            rubric_version=rubric_version,
            output_schema=output_schema,
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
    def _collect_rubric_fields(
        columns: Sequence[str],
        sort_field: str | None = None,
    ) -> dict[str, set[str]]:
        """Collect which fields are needed for each rubric.

        Returns a mapping of rubric_id -> set of field names.
        """
        rubric_fields: dict[str, set[str]] = {}
        all_columns = [*columns]
        if sort_field:
            all_columns.append(sort_field)

        for column in all_columns:
            rubric_info = CodeSampleService._parse_rubric_column(column)
            if rubric_info is not None:
                rubric_id, json_path = rubric_info
                if json_path:
                    field_name = json_path[0] if len(json_path) == 1 else "_".join(json_path)
                    rubric_fields.setdefault(rubric_id, set()).add(field_name)
        return rubric_fields

    @staticmethod
    def build_agent_runs_dql_query(
        *,
        columns: Sequence[str],
        sort_field: str | None,
        sort_direction: Literal["asc", "desc"],
        base_filter: ComplexFilter | None,
        limit: int | None,
        rubric_versions: Mapping[str, int] | None = None,
        table_alias: str = "ar",
    ) -> str:
        # Collect rubric IDs and fields, then build CTEs with mode() aggregation
        rubric_ids = sorted(CodeSampleService.collect_rubric_ids(columns, base_filter, sort_field))
        rubric_fields = CodeSampleService._collect_rubric_fields(columns, sort_field)
        rubric_ctes: list[str] = []
        rubric_sources: dict[str, str] = {}
        if rubric_ids:
            rubric_ctes, rubric_sources = CodeSampleService._build_rubric_ctes(
                rubric_ids,
                rubric_versions=rubric_versions,
                rubric_fields=rubric_fields,
            )

        # Collect label set IDs and build CTEs
        label_set_ids = sorted(
            CodeSampleService.collect_label_set_ids(columns, base_filter, sort_field)
        )
        label_ctes: list[str] = []
        label_sources: dict[str, str] = {}
        if label_set_ids:
            label_ctes, label_sources = CodeSampleService._build_label_ctes(label_set_ids)

        # Combine all CTEs
        all_ctes = rubric_ctes + label_ctes

        unique_columns: list[str] = []
        for col in ["agent_run_id", *columns]:
            if col not in unique_columns:
                unique_columns.append(col)

        select_lines = [
            CodeSampleService._build_select_expression(
                column,
                table_alias,
                rubric_versions=rubric_versions,
                rubric_sources=rubric_sources,
                label_sources=label_sources,
            )
            for column in unique_columns
        ]

        sort_expr = None
        if sort_field == "agent_run_id":
            sort_expr = f"{table_alias}.id"
        elif sort_field:
            sort_expr = CodeSampleService._build_field_expression(
                sort_field.split("."),
                table_alias,
                rubric_versions=rubric_versions,
                rubric_sources=rubric_sources,
                label_sources=label_sources,
            )
        if not sort_expr:
            sort_expr = f"{table_alias}.created_at"

        where_clause = CodeSampleService.build_where_clause(
            base_filter,
            table_alias,
            rubric_versions=rubric_versions,
            rubric_sources=rubric_sources,
            label_sources=label_sources,
        )

        # Build JOIN clauses for rubric CTEs
        join_clauses: list[str] = []
        for rubric_id in rubric_ids:
            cte_alias = rubric_sources.get(rubric_id)
            if cte_alias:
                join_clauses.append(
                    f"LEFT JOIN {cte_alias} ON {cte_alias}.agent_run_id = {table_alias}.id"
                )

        lines = [
            *(["WITH", ",\n".join(all_ctes)] if all_ctes else []),
            "SELECT",
            ",\n".join(f"  {line}" for line in select_lines),
            f"FROM agent_runs {table_alias}",
            *join_clauses,
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
        rubric_version: int,
        output_schema: Mapping[str, Any] | None,
        runs_filter: ComplexFilter | None,
        limit: int | None,
    ) -> str:
        where_clauses = [
            f"jr.rubric_id = '{CodeSampleService._escape_literal(rubric_id)}'",
        ]
        where_clauses.append(f"jr.rubric_version = {rubric_version}")

        run_filter_condition = (
            CodeSampleService._build_collection_filter_clause(
                runs_filter,
                "ar",
                rubric_versions=None,
                rubric_sources=None,
            )
            if runs_filter
            else None
        )
        if run_filter_condition:
            where_clauses.append(f"({run_filter_condition})")

        where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        output_select_lines = CodeSampleService._build_rubric_output_select_lines(
            output_schema=output_schema,
            table_alias="jr",
        )

        lines = [
            "SELECT",
            "  jr.id AS judge_result_id,",
            "  jr.agent_run_id,",
            "  jr.rubric_version,",
            "  jr.result_type,",
            *output_select_lines,
            "  jr.output AS output_json,",
            "  jr.result_metadata,",
            "  ar.created_at AS run_created_at,",
            "  ar.metadata_json AS run_metadata",
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
    def _build_rubric_output_select_lines(
        *,
        output_schema: Mapping[str, Any] | None,
        table_alias: str,
        max_fields: int = 20,
    ) -> list[str]:
        """Build SELECT lines for expected rubric output fields from a JSON schema.

        These fields are selected in addition to the raw output JSON so downstream users
        get a convenient, columnar view in pandas while still retaining full fidelity.
        """
        if not output_schema:
            return []

        properties_any = output_schema.get("properties")
        if not isinstance(properties_any, dict) or not properties_any:
            return []
        properties: dict[str, Any] = {}
        properties_any_typed = cast(dict[object, object], properties_any)
        for key_any, value_any in properties_any_typed.items():
            if isinstance(key_any, str):
                properties[key_any] = value_any
        if not properties:
            return []

        required_any = output_schema.get("required")
        required_fields: list[str] = []
        if isinstance(required_any, list):
            required_any_typed = cast(list[object], required_any)
            for item_any in required_any_typed:
                if isinstance(item_any, str):
                    required_fields.append(item_any)

        ordered_fields: list[str] = []
        for field in required_fields:
            if field in properties and field not in ordered_fields:
                ordered_fields.append(field)
        for field in sorted(properties.keys()):
            if field not in ordered_fields:
                ordered_fields.append(field)

        lines: list[str] = []
        for field in ordered_fields[: max(0, int(max_fields))]:
            schema_fragment_any = properties.get(field)
            fragment: dict[str, Any] = {}
            if isinstance(schema_fragment_any, dict):
                schema_fragment_any_typed = cast(dict[object, object], schema_fragment_any)
                for key_any, value_any in schema_fragment_any_typed.items():
                    if isinstance(key_any, str):
                        fragment[key_any] = value_any
            expr = CodeSampleService._build_json_schema_accessor(
                base=f"{table_alias}.output",
                field=field,
                schema_fragment=fragment,
            )
            alias = CodeSampleService._sanitize_identifier(f"output_{field}")
            lines.append(f"  {expr} AS {alias},")
        return lines

    @staticmethod
    def _build_json_schema_accessor(
        *,
        base: str,
        field: str,
        schema_fragment: Mapping[str, Any],
    ) -> str:
        """Build a SQL expression that extracts a JSON field, casting when helpful."""
        escaped = CodeSampleService._escape_literal(field)
        json_type = schema_fragment.get("type")
        types: list[str] = []
        if isinstance(json_type, str):
            types = [json_type]
        elif isinstance(json_type, list):
            json_type_typed = cast(list[object], json_type)
            for item_any in json_type_typed:
                if isinstance(item_any, str):
                    types.append(item_any)

        is_complex = any(t in {"object", "array"} for t in types)
        if is_complex:
            return f"{base}->'{escaped}'"

        text_expr = f"{base}->>'{escaped}'"
        if "boolean" in types:
            return f"CAST({text_expr} AS BOOLEAN)"
        if "integer" in types:
            return f"CAST({text_expr} AS BIGINT)"
        if "number" in types:
            return f"CAST({text_expr} AS DOUBLE PRECISION)"
        return text_expr

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        sanitized: list[str] = []
        for ch in value:
            if ch.isalnum() or ch == "_":
                sanitized.append(ch)
            else:
                sanitized.append("_")
        candidate = "".join(sanitized).strip("_")
        return candidate or "field"

    @staticmethod
    def collect_rubric_ids(
        columns: Sequence[str],
        base_filter: ComplexFilter | None,
        sort_field: str | None = None,
    ) -> set[str]:
        rubric_ids: set[str] = set()
        for column in columns:
            rubric_info = CodeSampleService._parse_rubric_column(column)
            if rubric_info is not None:
                rubric_ids.add(rubric_info[0])
        if sort_field:
            rubric_info = CodeSampleService._parse_rubric_column(sort_field)
            if rubric_info is not None:
                rubric_ids.add(rubric_info[0])
        if base_filter:
            rubric_ids.update(CodeSampleService._collect_rubric_ids_from_filter(base_filter))
        return rubric_ids

    @staticmethod
    def _collect_rubric_ids_from_filter(filter_obj: CollectionFilter) -> set[str]:
        if getattr(filter_obj, "disabled", False):
            return set()
        if isinstance(filter_obj, PrimitiveFilter):
            if filter_obj.key_path and filter_obj.key_path[0] == "rubric":
                if len(filter_obj.key_path) >= 2:
                    return {filter_obj.key_path[1]}
            return set()
        if isinstance(filter_obj, ComplexFilter):
            rubric_ids: set[str] = set()
            for sub_filter in filter_obj.filters:
                rubric_ids.update(CodeSampleService._collect_rubric_ids_from_filter(sub_filter))
            return rubric_ids
        # AgentRunIdFilter doesn't contain rubric IDs
        return set()

    @staticmethod
    def collect_label_set_ids(
        columns: Sequence[str],
        base_filter: ComplexFilter | None,
        sort_field: str | None = None,
    ) -> set[str]:
        """Collect label set IDs from columns, filters, and sort field."""
        label_set_ids: set[str] = set()
        for column in columns:
            label_info = CodeSampleService._parse_label_column(column)
            if label_info is not None:
                label_set_ids.add(label_info[0])
        if sort_field:
            label_info = CodeSampleService._parse_label_column(sort_field)
            if label_info is not None:
                label_set_ids.add(label_info[0])
        if base_filter:
            label_set_ids.update(CodeSampleService._collect_label_set_ids_from_filter(base_filter))
        return label_set_ids

    @staticmethod
    def _collect_label_set_ids_from_filter(filter_obj: CollectionFilter) -> set[str]:
        """Collect label set IDs from a filter object."""
        if getattr(filter_obj, "disabled", False):
            return set()
        if isinstance(filter_obj, PrimitiveFilter):
            if filter_obj.key_path and filter_obj.key_path[0] == "label":
                if len(filter_obj.key_path) >= 2:
                    return {filter_obj.key_path[1]}
            return set()
        if isinstance(filter_obj, ComplexFilter):
            label_set_ids: set[str] = set()
            for sub_filter in filter_obj.filters:
                label_set_ids.update(
                    CodeSampleService._collect_label_set_ids_from_filter(sub_filter)
                )
            return label_set_ids
        # AgentRunIdFilter doesn't contain label set IDs
        return set()

    @staticmethod
    def build_where_clause(
        filter_obj: ComplexFilter | None,
        table_alias: str,
        rubric_versions: Mapping[str, int] | None = None,
        rubric_sources: Mapping[str, str] | None = None,
        label_sources: Mapping[str, str] | None = None,
    ) -> str:
        if not filter_obj:
            return ""
        condition = CodeSampleService._build_collection_filter_clause(
            filter_obj,
            table_alias,
            rubric_versions=rubric_versions,
            rubric_sources=rubric_sources,
            label_sources=label_sources,
        )
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
    def _build_tag_list_expression(table_alias: str) -> str:
        return (
            "(SELECT array_agg(t.value ORDER BY t.value) "
            "FROM tags t "
            f"WHERE t.agent_run_id = {table_alias}.id "
            f"AND t.collection_id = {table_alias}.collection_id)"
        )

    @staticmethod
    def _parse_label_column(column: str) -> tuple[str, list[str]] | None:
        """Parse a label column like 'label.{label_set_id}.{json_path}'.

        Returns (label_set_id, json_path) or None if not a label column.
        """
        if not column.startswith("label."):
            return None
        parts = column.split(".")
        if len(parts) < 3:
            return None
        label_set_id = parts[1]
        if not label_set_id:
            return None
        return label_set_id, parts[2:]

    @staticmethod
    def _build_label_expression(
        label_set_id: str,
        json_path: Sequence[str],
        table_alias: str,
        comparison_value: object | None = None,
        label_sources: Mapping[str, str] | None = None,
    ) -> str:
        """Build a subquery expression to fetch a label value for an agent run."""
        if not json_path:
            raise ValueError("Label path cannot be empty")

        label_source = label_sources.get(label_set_id) if label_sources else None
        value_expr = CodeSampleService._build_json_text_accessor("l.label_value", json_path)

        if label_source:
            # Use CTE alias
            subquery = (
                f"(SELECT {value_expr} "
                f"FROM {label_source} l "
                f"WHERE l.agent_run_id = {table_alias}.id)"
            )
        else:
            # Fallback to direct table query
            escaped_label_set_id = CodeSampleService._escape_literal(label_set_id)
            subquery = (
                f"(SELECT {value_expr} "
                "FROM labels l "
                f"WHERE l.agent_run_id = {table_alias}.id "
                f"AND l.label_set_id = '{escaped_label_set_id}')"
            )

        if isinstance(comparison_value, (int, float)):
            return f"CAST({subquery} AS DOUBLE PRECISION)"
        if isinstance(comparison_value, bool):
            return f"CAST({subquery} AS BOOLEAN)"
        return subquery

    @staticmethod
    def _build_label_filter_clause(
        filter_obj: PrimitiveFilter,
        table_alias: str,
        label_sources: Mapping[str, str] | None = None,
    ) -> str | None:
        """Build a filter clause for label filters."""
        if len(filter_obj.key_path) < 3:
            raise ValueError("Label filters must include a JSON field path.")

        label_set_id = filter_obj.key_path[1]
        json_path = filter_obj.key_path[2:]
        label_source = label_sources.get(label_set_id) if label_sources else None
        value_expr = CodeSampleService._build_json_text_accessor("l.label_value", json_path)

        if label_source:
            # Use CTE alias
            from_clause = f"{label_source} l"
            where_base = f"l.agent_run_id = {table_alias}.id"
        else:
            # Fallback to direct table query
            escaped_label_set_id = CodeSampleService._escape_literal(label_set_id)
            from_clause = "labels l"
            where_base = (
                f"l.agent_run_id = {table_alias}.id AND l.label_set_id = '{escaped_label_set_id}'"
            )

        op = str(filter_obj.op)
        if op == "is":
            normalized = (
                filter_obj.value.strip().lower() if isinstance(filter_obj.value, str) else None
            )
            if normalized == "null":
                # Check if no label exists OR label value is null
                return (
                    "NOT EXISTS ("
                    f"SELECT 1 FROM {from_clause} "
                    f"WHERE {where_base} "
                    f"AND {value_expr} IS NOT NULL)"
                )
            if normalized == "not null":
                return (
                    "EXISTS ("
                    f"SELECT 1 FROM {from_clause} "
                    f"WHERE {where_base} "
                    f"AND {value_expr} IS NOT NULL)"
                )
            formatted_value = CodeSampleService._format_value(filter_obj.value)
            return (
                "EXISTS ("
                f"SELECT 1 FROM {from_clause} "
                f"WHERE {where_base} "
                f"AND {value_expr} IS {formatted_value})"
            )

        formatted_value = CodeSampleService._format_value(filter_obj.value)
        if op in {"==", "!=", ">", ">=", "<", "<=", "~*", "!~*"}:
            sql_op = "=" if op == "==" else op
            return (
                "EXISTS ("
                f"SELECT 1 FROM {from_clause} "
                f"WHERE {where_base} "
                f"AND {value_expr} {sql_op} {formatted_value})"
            )

        return None

    @staticmethod
    def _build_tag_sort_expression(table_alias: str) -> str:
        return (
            "(SELECT string_agg(t.value, ',' ORDER BY t.value) "
            "FROM tags t "
            f"WHERE t.agent_run_id = {table_alias}.id "
            f"AND t.collection_id = {table_alias}.collection_id)"
        )

    @staticmethod
    def _build_tag_filter_clause(
        filter_obj: PrimitiveFilter,
        table_alias: str,
    ) -> str | None:
        if len(filter_obj.key_path) != 1:
            raise ValueError("Tag filters do not support nested paths.")

        op = str(filter_obj.op)
        if op == "is":
            normalized = (
                filter_obj.value.strip().lower() if isinstance(filter_obj.value, str) else None
            )
            if normalized == "null":
                return (
                    "NOT EXISTS ("
                    "SELECT 1 FROM tags t "
                    f"WHERE t.agent_run_id = {table_alias}.id "
                    f"AND t.collection_id = {table_alias}.collection_id)"
                )
            if normalized == "not null":
                return (
                    "EXISTS ("
                    "SELECT 1 FROM tags t "
                    f"WHERE t.agent_run_id = {table_alias}.id "
                    f"AND t.collection_id = {table_alias}.collection_id)"
                )
            formatted_value = CodeSampleService._format_value(filter_obj.value)
            return (
                "EXISTS ("
                "SELECT 1 FROM tags t "
                f"WHERE t.agent_run_id = {table_alias}.id "
                f"AND t.collection_id = {table_alias}.collection_id "
                f"AND t.value IS {formatted_value})"
            )

        formatted_value = CodeSampleService._format_value(filter_obj.value)
        if op in {"==", "!=", ">", ">=", "<", "<=", "~*", "!~*"}:
            sql_op = "=" if op == "==" else op
            return (
                "EXISTS ("
                "SELECT 1 FROM tags t "
                f"WHERE t.agent_run_id = {table_alias}.id "
                f"AND t.collection_id = {table_alias}.collection_id "
                f"AND t.value {sql_op} {formatted_value})"
            )

        return None

    @staticmethod
    def _build_json_text_accessor(base: str, path: Sequence[str]) -> str:
        if not path:
            raise ValueError("JSON path cannot be empty")
        accessor = base
        for segment in path[:-1]:
            accessor = f"{accessor}->'{CodeSampleService._escape_literal(segment)}'"
        last_segment = CodeSampleService._escape_literal(path[-1])
        return f"{accessor}->>'{last_segment}'"

    @staticmethod
    def _build_rubric_version_clause(rubric_id: str, rubric_version: int | None) -> str:
        if rubric_version is not None:
            return f"jr.rubric_version = {int(rubric_version)}"
        escaped_id = CodeSampleService._escape_literal(rubric_id)
        result_type = CodeSampleService._escape_literal(ResultType.DIRECT_RESULT.value)
        return (
            "jr.rubric_version = ("
            "SELECT MAX(jr_version.rubric_version) "
            "FROM judge_results jr_version "
            f"WHERE jr_version.rubric_id = '{escaped_id}' "
            f"AND jr_version.result_type = '{result_type}'"
            ")"
        )

    @staticmethod
    def _build_rubric_modal_expression(
        rubric_id: str,
        json_path: Sequence[str],
        table_alias: str,
        rubric_versions: Mapping[str, int] | None = None,
        rubric_sources: Mapping[str, str] | None = None,
        comparison_value: object | None = None,
    ) -> str:
        """Build expression to get the modal value for a rubric field.

        When a CTE exists (rubric_sources), references the pre-computed column directly.
        Otherwise, falls back to a subquery approach.
        """
        if not json_path:
            raise ValueError("Rubric path cannot be empty")

        rubric_source = rubric_sources.get(rubric_id) if rubric_sources else None

        if rubric_source:
            # Use the pre-computed modal value from the CTE
            # The CTE has columns like: agent_run_id, label, explanation, etc.
            field_name = json_path[0] if len(json_path) == 1 else "_".join(json_path)
            sanitized_field = CodeSampleService._sanitize_identifier(field_name)
            # The CTE alias will be joined in the FROM clause
            modal_expr = f"{rubric_source}.{sanitized_field}"
        else:
            # Fallback to subquery approach (for filters or when no CTE)
            value_expr = CodeSampleService._build_json_text_accessor("jr.output", json_path)
            rubric_version = rubric_versions.get(rubric_id) if rubric_versions else None
            version_clause = CodeSampleService._build_rubric_version_clause(
                rubric_id, rubric_version
            )
            escaped_id = CodeSampleService._escape_literal(rubric_id)
            result_type = CodeSampleService._escape_literal(ResultType.DIRECT_RESULT.value)
            where_clauses = [
                f"jr.agent_run_id = {table_alias}.id",
                f"jr.rubric_id = '{escaped_id}'",
                version_clause,
                f"jr.result_type = '{result_type}'",
            ]
            where_sql = " AND ".join(where_clauses)
            modal_expr = (
                "(SELECT rubric_counts.rubric_value "
                "FROM ("
                f"SELECT {value_expr} AS rubric_value, COUNT(1) AS value_count "
                "FROM judge_results jr "
                f"WHERE {where_sql} "
                f"GROUP BY {value_expr}"
                ") rubric_counts "
                "ORDER BY rubric_counts.value_count DESC, "
                "rubric_counts.rubric_value ASC NULLS LAST "
                "LIMIT 1)"
            )

        if isinstance(comparison_value, (int, float)):
            return f"CAST({modal_expr} AS DOUBLE PRECISION)"
        if isinstance(comparison_value, bool):
            return f"CAST({modal_expr} AS BOOLEAN)"
        return modal_expr

    @staticmethod
    def _parse_rubric_column(column: str) -> tuple[str, list[str]] | None:
        if not column.startswith("rubric."):
            return None
        parts = column.split(".")
        if len(parts) < 3:
            return None
        rubric_id = parts[1]
        if not rubric_id:
            return None
        return rubric_id, parts[2:]

    @staticmethod
    def _build_field_expression(
        key_path: Sequence[str],
        table_alias: str,
        comparison_value: object | None = None,
        rubric_versions: Mapping[str, int] | None = None,
        rubric_sources: Mapping[str, str] | None = None,
        label_sources: Mapping[str, str] | None = None,
    ) -> str | None:
        if not key_path:
            return None

        root, *rest = key_path
        if root == "metadata":
            if not rest:
                return None
            return CodeSampleService._build_metadata_accessor(rest, table_alias, comparison_value)
        if root == "rubric":
            if len(rest) < 2:
                return None
            rubric_id = rest[0]
            json_path = rest[1:]
            return CodeSampleService._build_rubric_modal_expression(
                rubric_id,
                json_path,
                table_alias,
                rubric_versions=rubric_versions,
                rubric_sources=rubric_sources,
                comparison_value=comparison_value,
            )
        if root == "tag":
            if rest:
                return None
            return CodeSampleService._build_tag_sort_expression(table_alias)
        if root == "label":
            if len(rest) < 2:
                return None
            label_set_id = rest[0]
            json_path = rest[1:]
            return CodeSampleService._build_label_expression(
                label_set_id,
                json_path,
                table_alias,
                comparison_value=comparison_value,
                label_sources=label_sources,
            )
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
    def _build_primitive_clause(
        filter_obj: PrimitiveFilter,
        table_alias: str,
        rubric_versions: Mapping[str, int] | None = None,
        rubric_sources: Mapping[str, str] | None = None,
        label_sources: Mapping[str, str] | None = None,
    ) -> str | None:
        if filter_obj.disabled or filter_obj.supports_sql is False:
            return None

        if filter_obj.key_path and filter_obj.key_path[0] == "tag":
            return CodeSampleService._build_tag_filter_clause(filter_obj, table_alias)

        if filter_obj.key_path and filter_obj.key_path[0] == "label":
            return CodeSampleService._build_label_filter_clause(
                filter_obj, table_alias, label_sources=label_sources
            )

        field_expr = CodeSampleService._build_field_expression(
            filter_obj.key_path,
            table_alias,
            filter_obj.value,
            rubric_versions=rubric_versions,
            rubric_sources=rubric_sources,
            label_sources=label_sources,
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
        filter_obj: CollectionFilter,
        table_alias: str,
        rubric_versions: Mapping[str, int] | None = None,
        rubric_sources: Mapping[str, str] | None = None,
        label_sources: Mapping[str, str] | None = None,
    ) -> str | None:
        if (
            getattr(filter_obj, "disabled", False)
            or getattr(filter_obj, "supports_sql", True) is False
        ):
            return None

        if isinstance(filter_obj, PrimitiveFilter):
            return CodeSampleService._build_primitive_clause(
                filter_obj,
                table_alias,
                rubric_versions=rubric_versions,
                rubric_sources=rubric_sources,
                label_sources=label_sources,
            )
        if isinstance(filter_obj, AgentRunIdFilter):
            return CodeSampleService._build_agent_run_id_clause(filter_obj, table_alias)

        # Remaining supported type is ComplexFilter
        inner = [
            clause
            for clause in (
                CodeSampleService._build_collection_filter_clause(
                    child,
                    table_alias,
                    rubric_versions=rubric_versions,
                    rubric_sources=rubric_sources,
                    label_sources=label_sources,
                )
                for child in getattr(filter_obj, "filters", [])
            )
            if clause
        ]
        if not inner:
            return None
        joiner = " OR " if getattr(filter_obj, "op", "and") == "or" else " AND "
        return f"({joiner.join(inner)})"

    @staticmethod
    def _build_select_expression(
        column: str,
        table_alias: str,
        rubric_versions: Mapping[str, int] | None = None,
        rubric_sources: Mapping[str, str] | None = None,
        label_sources: Mapping[str, str] | None = None,
    ) -> str:
        if column == "agent_run_id":
            return f"{table_alias}.id AS agent_run_id"
        if column == "tag":
            expr = CodeSampleService._build_tag_list_expression(table_alias)
            return f"{expr} AS tag"
        if column.startswith("metadata."):
            path = column.split(".")[1:]
            expr = CodeSampleService._build_metadata_accessor(path, table_alias)
            alias = column.replace(".", "_")
            return f"{expr} AS {alias}"
        if column.startswith("rubric."):
            rubric_info = CodeSampleService._parse_rubric_column(column)
            if rubric_info is None:
                parts = column.split(".")
                if len(parts) >= 2 and parts[1]:
                    alias = CodeSampleService._build_rubric_column_alias(
                        parts[1],
                        parts[2:],
                        rubric_sources=rubric_sources,
                    )
                else:
                    alias = CodeSampleService._sanitize_identifier(column.replace(".", "_"))
                return f"NULL AS {alias}"
            rubric_id, json_path = rubric_info
            expr = CodeSampleService._build_rubric_modal_expression(
                rubric_id,
                json_path,
                table_alias,
                rubric_versions=rubric_versions,
                rubric_sources=rubric_sources,
            )
            alias = CodeSampleService._build_rubric_column_alias(
                rubric_id,
                json_path,
                rubric_sources=rubric_sources,
            )
            return f"{expr} AS {alias}"
        if column.startswith("label."):
            label_info = CodeSampleService._parse_label_column(column)
            if label_info is None:
                alias = CodeSampleService._sanitize_identifier(column.replace(".", "_"))
                return f"NULL AS {alias}"
            label_set_id, json_path = label_info
            expr = CodeSampleService._build_label_expression(
                label_set_id,
                json_path,
                table_alias,
                label_sources=label_sources,
            )
            # Build alias using CTE name if available, otherwise use short ID
            alias = CodeSampleService._build_label_column_alias(
                label_set_id,
                json_path,
                label_sources=label_sources,
            )
            return f"{expr} AS {alias}"
        return f"{table_alias}.{column} AS {column}"

    @staticmethod
    def _build_rubric_column_alias(
        rubric_id: str,
        json_path: Sequence[str],
        rubric_sources: Mapping[str, str] | None = None,
    ) -> str:
        prefix = rubric_sources.get(rubric_id) if rubric_sources else None
        if not prefix:
            short_id = rubric_id.split("-", maxsplit=1)[0]
            prefix = CodeSampleService._sanitize_identifier(f"rubric_{short_id}")
        parts = [prefix, *[part for part in json_path if part]]
        return CodeSampleService._sanitize_identifier("_".join(parts))

    @staticmethod
    def _build_label_column_alias(
        label_set_id: str,
        json_path: Sequence[str],
        label_sources: Mapping[str, str] | None = None,
    ) -> str:
        """Build a column alias for label columns, using CTE name if available."""
        prefix = label_sources.get(label_set_id) if label_sources else None
        if not prefix:
            short_id = label_set_id.split("-", maxsplit=1)[0]
            prefix = CodeSampleService._sanitize_identifier(f"label_{short_id}")
        parts = [prefix, *[part for part in json_path if part]]
        return CodeSampleService._sanitize_identifier("_".join(parts))

    @staticmethod
    def _build_rubric_ctes(
        rubric_ids: Sequence[str],
        rubric_versions: Mapping[str, int] | None = None,
        rubric_fields: Mapping[str, set[str]] | None = None,
    ) -> tuple[list[str], dict[str, str]]:
        """Build CTEs for rubrics using mode() WITHIN GROUP for multiple rollouts.

        Args:
            rubric_ids: List of rubric IDs to build CTEs for
            rubric_versions: Mapping of rubric_id -> version number
            rubric_fields: Mapping of rubric_id -> set of field names to extract
        """
        ctes: list[str] = []
        alias_map: dict[str, str] = {}
        alias_counts: dict[str, int] = {}
        for rubric_id in rubric_ids:
            short_id = rubric_id.split("-", maxsplit=1)[0]
            base_alias = CodeSampleService._sanitize_identifier(f"rubric_{short_id}_modes")
            alias_index = alias_counts.get(base_alias, 0)
            alias_counts[base_alias] = alias_index + 1
            alias = base_alias if alias_index == 0 else f"{base_alias}_{alias_index}"
            alias_map[rubric_id] = alias
            escaped_id = CodeSampleService._escape_literal(rubric_id)
            rubric_version = rubric_versions.get(rubric_id) if rubric_versions else None
            version_clause = CodeSampleService._build_rubric_version_clause(
                rubric_id, rubric_version
            )
            result_type = CodeSampleService._escape_literal(ResultType.DIRECT_RESULT.value)

            # Build mode() expressions for each requested field
            fields: set[str] = rubric_fields.get(rubric_id, set()) if rubric_fields else set()
            if not fields:
                # Default to common fields if none specified
                fields = {"label", "explanation"}

            mode_lines: list[str] = []
            for field in sorted(fields):
                escaped_field = CodeSampleService._escape_literal(field)
                mode_lines.append(
                    f"    mode() WITHIN GROUP (ORDER BY jr.output->>'{escaped_field}') "
                    f"AS {CodeSampleService._sanitize_identifier(field)}"
                )

            mode_clause = ",\n".join(mode_lines)

            cte = "\n".join(
                [
                    f"  {alias} AS (",
                    "    SELECT",
                    "      jr.agent_run_id,",
                    mode_clause,
                    "    FROM judge_results jr",
                    f"    WHERE jr.rubric_id = '{escaped_id}'",
                    f"      AND {version_clause}",
                    f"      AND jr.result_type = '{result_type}'",
                    "    GROUP BY jr.agent_run_id",
                    "  )",
                ]
            )
            ctes.append(cte)
        return ctes, alias_map

    @staticmethod
    def _build_label_ctes(
        label_set_ids: Sequence[str],
    ) -> tuple[list[str], dict[str, str]]:
        """Build CTEs for label sets, returning (cte_strings, label_set_id -> alias map)."""
        ctes: list[str] = []
        alias_map: dict[str, str] = {}
        alias_counts: dict[str, int] = {}
        for label_set_id in label_set_ids:
            short_id = label_set_id.split("-", maxsplit=1)[0]
            base_alias = CodeSampleService._sanitize_identifier(f"label_{short_id}")
            alias_index = alias_counts.get(base_alias, 0)
            alias_counts[base_alias] = alias_index + 1
            alias = base_alias if alias_index == 0 else f"{base_alias}_{alias_index}"
            alias_map[label_set_id] = alias
            escaped_id = CodeSampleService._escape_literal(label_set_id)
            cte = "\n".join(
                [
                    f"  {alias} AS (",
                    "    SELECT l.agent_run_id, l.label_value",
                    "    FROM labels l",
                    f"    WHERE l.label_set_id = '{escaped_id}'",
                    "  )",
                ]
            )
            ctes.append(cte)
        return ctes, alias_map
