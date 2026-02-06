from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause
from sqlglot import exp

from docent_core.docent.db.dql import (
    DQL_COLLECTION_SETTING_KEY,
    CollectionPredicateFactory,
    ColumnReference,
    DQLRegistry,
    DQLValidationError,
    JsonFieldInfo,
    QueryExpression,
    SelectedColumn,
    SqlGlotExpression,
    apply_limit_cap,
    build_collection_sqla_query,
    build_default_registry,
    get_query_limit_value,
    get_selected_columns,
    json_field_info_to_expression,
    parse_dql_query,
)
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import SQLAAgentRun
from docent_core.docent.services.dql import DEFAULT_DQL_MAX_ROWS, DQLService

COLLECTION_ID = "test-collection"
TEST_USER = User(id="user-1", email="user@example.com", organization_ids=[], is_anonymous=False)


def _collection_predicate_for(column_name: str) -> CollectionPredicateFactory:
    def builder(table_alias: str, collection_id: str) -> SqlGlotExpression:
        return exp.EQ(
            this=exp.column(column_name, table=table_alias),
            expression=exp.Literal.string(collection_id),  # type: ignore[reportUnknownMemberType]
        )

    return builder


class DummyMonoService:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str]] = []

    async def has_permission(
        self,
        *,
        user: User,
        resource_type: str,
        resource_id: str,
        permission: str,
    ) -> bool:
        self.calls.append((str(resource_type), resource_id))
        return self.allowed


def test_build_sqla_query_basic_select() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    query = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql=(
                "SELECT id, created_at FROM agent_runs "
                "WHERE id = 'abc' ORDER BY created_at DESC LIMIT 5 OFFSET 2"
            ),
            registry=registry,
        )
    )

    assert isinstance(query, TextClause)
    expected_sql = (
        "SELECT id, created_at FROM agent_runs "
        "WHERE id = :__dql_param_3 AND agent_runs.collection_id = :__dql_param_4 "
        "ORDER BY created_at DESC LIMIT (:__dql_param_1)::integer "
        "OFFSET (:__dql_param_2)::integer"
    )
    assert query.text == expected_sql
    compiled = query.compile()
    assert compiled.params == {
        "__dql_param_1": 5,
        "__dql_param_2": 2,
        "__dql_param_3": "abc",
        "__dql_param_4": COLLECTION_ID,
    }


def test_invalid_column_raises_validation_error() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        asyncio.run(
            build_collection_sqla_query(
                mono_service=DummyMonoService(True),  # type: ignore[arg-type]
                user=TEST_USER,
                collection_id=COLLECTION_ID,
                dql="SELECT invalid_column FROM agent_runs",
                registry=registry,
            )
        )


def test_subquery_validation_passes() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    query = """
        SELECT sub.id
        FROM (
            SELECT ar.id
            FROM agent_runs ar
            WHERE ar.created_at > '2024-01-01'
        ) sub
        WHERE sub.id IN (
            SELECT ar2.id FROM agent_runs ar2 WHERE ar2.name = 'foo'
        )
    """
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql=query,
            registry=registry,
        )
    )
    assert isinstance(clause, TextClause)
    assert "SELECT ar2.id FROM agent_runs AS ar2" in clause.text


def test_where_clause_parsing_supports_in_and_not_like() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    # Test that DQL parsing supports IN and NOT LIKE operators
    dql = "SELECT id FROM agent_runs WHERE agent_runs.id IN ('a', 'b') AND NOT agent_runs.name ILIKE '%test%'"
    expression = parse_dql_query(dql, registry=registry, collection_id=COLLECTION_ID)
    assert expression is not None


def test_negative_limit_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        asyncio.run(
            build_collection_sqla_query(
                mono_service=DummyMonoService(True),  # type: ignore[arg-type]
                user=TEST_USER,
                collection_id=COLLECTION_ID,
                dql="SELECT id FROM agent_runs LIMIT -1",
                registry=registry,
            )
        )


def test_wildcard_selection_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        asyncio.run(
            build_collection_sqla_query(
                mono_service=DummyMonoService(True),  # type: ignore[arg-type]
                user=TEST_USER,
                collection_id=COLLECTION_ID,
                dql="SELECT * FROM agent_runs",
                registry=registry,
            )
        )


def test_where_clause_requires_qualifier() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    # Single table queries should allow unqualified columns
    parse_dql_query(
        "SELECT id FROM agent_runs WHERE id = 'foo'",
        registry=registry,
        collection_id=COLLECTION_ID,
    )

    # Multi-table queries should require qualified columns
    with pytest.raises(DQLValidationError):
        parse_dql_query(
            "SELECT id FROM agent_runs ar JOIN transcripts t ON t.agent_run_id = ar.id WHERE id = 'foo'",
            registry=registry,
            collection_id=COLLECTION_ID,
        )


def test_disallow_modification_statements() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        parse_dql_query(
            "DELETE FROM agent_runs WHERE id = 'x'", registry=registry, collection_id=COLLECTION_ID
        )


def test_select_allows_table_alias_and_table_name() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    # should not raise
    parse_dql_query(
        "SELECT agent_runs.id FROM agent_runs ar", registry=registry, collection_id=COLLECTION_ID
    )


def test_get_selected_columns_includes_alias_metadata() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    columns = get_selected_columns(
        "SELECT ar.id AS run_id, ar.created_at FROM agent_runs ar",
        registry=registry,
        collection_id=COLLECTION_ID,
    )

    assert columns == [
        SelectedColumn(
            output_name="run_id",
            expression_sql="ar.id AS run_id",
            source_columns=(ColumnReference(table="agent_runs", column="id"),),
        ),
        SelectedColumn(
            output_name="created_at",
            expression_sql="ar.created_at",
            source_columns=(ColumnReference(table="agent_runs", column="created_at"),),
        ),
    ]


def test_unregistered_table_select_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        parse_dql_query(
            "SELECT password FROM users", registry=registry, collection_id=COLLECTION_ID
        )


def test_unregistered_table_in_subquery_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        parse_dql_query(
            "SELECT id FROM agent_runs WHERE EXISTS (SELECT 1 FROM users)",
            registry=registry,
            collection_id=COLLECTION_ID,
        )


def test_count_without_argument_rewritten_to_literal_one() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="SELECT count() FROM agent_runs",
            registry=registry,
        )
    )
    assert "COUNT((:__dql_param_1)::integer)" in clause.text
    assert "*" not in clause.text


def test_order_by_desc_unchanged_by_expression_sugar() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="SELECT id, name, created_at FROM agent_runs ORDER BY created_at DESC LIMIT 20",
            registry=registry,
        )
    )
    assert "DESC1" not in clause.text
    assert "ORDER BY created_at DESC" in clause.text


def test_union_with_unregistered_table_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        parse_dql_query(
            "SELECT id FROM agent_runs UNION SELECT password FROM users",
            registry=registry,
            collection_id=COLLECTION_ID,
        )


def test_cte_allowed_and_scoped() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="""
            WITH recent AS (
                SELECT id, created_at
                FROM agent_runs
                WHERE created_at > '2024-01-01'
            )
            SELECT id FROM recent
            """,
            registry=registry,
        )
    )

    assert "WITH recent AS" in clause.text
    assert "agent_runs.collection_id = :__dql_param_" in clause.text
    bound_values = {name: bind.value for name, bind in getattr(clause, "_bindparams", {}).items()}
    assert COLLECTION_ID in bound_values.values()


def test_doc_sql_examples_compile() -> None:
    doc_queries = [
        (
            "recent_runs",
            """
            SELECT
              id,
              name,
              metadata_json->'model'->>'name' AS model_name,
              created_at
            FROM agent_runs
            WHERE metadata_json->>'status' = 'completed'
            ORDER BY created_at DESC
            LIMIT 10
            """,
        ),
        (
            "transcript_group_counts",
            """
            SELECT
              tg.id AS group_id,
              tg.name AS group_name,
              COUNT(t.id) AS transcript_count
            FROM transcript_groups tg
            JOIN transcripts t ON t.transcript_group_id = tg.id
            GROUP BY tg.id, tg.name
            HAVING COUNT(t.id) > 1
            ORDER BY transcript_count DESC
            """,
        ),
        (
            "flagged_judge_results",
            """
            SELECT
              jr.agent_run_id,
              jr.rubric_id,
              jr.result_metadata->>'label' AS label,
              jr.output->>'score' AS score
            FROM judge_results jr
            WHERE jr.result_metadata->>'severity' = 'high'
              AND EXISTS (
                SELECT 1
                FROM agent_runs ar
                WHERE ar.id = jr.agent_run_id
                  AND ar.metadata_json->>'environment' = 'prod'
              )
            ORDER BY score DESC
            LIMIT 25
            """,
        ),
        (
            "metadata_filter",
            """
            SELECT id, name
            FROM agent_runs
            WHERE metadata_json->>'environment' = 'staging'
            """,
        ),
        (
            "metadata_nested",
            """
            SELECT
              id,
              metadata_json->'conversation'->>'speaker' AS speaker,
              metadata_json->'conversation'->>'topic' AS topic
            FROM transcripts
            WHERE metadata_json->>'status' = 'flagged'
            """,
        ),
        (
            "metadata_avg_latency",
            """
            SELECT
              AVG(CAST(metadata_json->>'latency_ms' AS DOUBLE PRECISION)) AS avg_latency_ms
            FROM agent_runs
            WHERE metadata_json ? 'latency_ms'
            """,
        ),
    ]

    registry = build_default_registry(collection_id=COLLECTION_ID)
    for name, query in doc_queries:
        clause = asyncio.run(
            build_collection_sqla_query(
                mono_service=DummyMonoService(True),  # type: ignore[arg-type]
                user=TEST_USER,
                collection_id=COLLECTION_ID,
                dql=query,
                registry=registry,
            )
        )
        assert clause.text, f"Expected compiled SQL for example '{name}'"


def test_common_aggregate_functions_compile() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    aggregate_queries = [
        "SELECT ARRAY_AGG(id) FROM agent_runs",
        """
        SELECT
          STDDEV(CAST(metadata_json->>'latency_ms' AS DOUBLE PRECISION))
        FROM agent_runs
        """,
        """
        SELECT
          VARIANCE(CAST(metadata_json->>'latency_ms' AS DOUBLE PRECISION))
        FROM agent_runs
        """,
        "SELECT AVG(metadata_json->'scores'->'accuracy') FROM agent_runs",
        "SELECT PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY created_at) FROM agent_runs",
    ]

    for query in aggregate_queries:
        clause = asyncio.run(
            build_collection_sqla_query(
                mono_service=DummyMonoService(True),  # type: ignore[arg-type]
                user=TEST_USER,
                collection_id=COLLECTION_ID,
                dql=query,
                registry=registry,
            )
        )
        assert clause.text


def test_column_alias_metadata_allowed() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    parse_dql_query(
        "SELECT metadata FROM agent_runs", registry=registry, collection_id=COLLECTION_ID
    )
    parse_dql_query(
        "SELECT id FROM agent_runs WHERE metadata IS NOT NULL",
        registry=registry,
        collection_id=COLLECTION_ID,
    )
    table = registry.get_table(SQLAAgentRun.__tablename__)
    assert table.column_aliases.get("metadata") == "metadata_json"


def test_table_alias_registration() -> None:
    registry = DQLRegistry()
    registry.register_table(
        name=SQLAAgentRun.__tablename__,
        table=SQLAAgentRun.__table__,
        allowed_columns=(
            "id",
            "collection_id",
            "name",
            "description",
            "metadata_json",
            "created_at",
            "text_for_search",
        ),
        collection_predicate_factory=_collection_predicate_for("collection_id"),
        aliases=["agent_run_records"],
        column_aliases={"metadata": "metadata_json"},
    )
    parse_dql_query(
        "SELECT id FROM agent_run_records", registry=registry, collection_id=COLLECTION_ID
    )
    parse_dql_query(
        "SELECT metadata FROM agent_run_records WHERE metadata IS NOT NULL",
        registry=registry,
        collection_id=COLLECTION_ID,
    )
    table = registry.get_table("agent_run_records")
    assert table.name == SQLAAgentRun.__tablename__.lower()
    assert table.column_aliases.get("metadata") == "metadata_json"


def test_metadata_field_mapping_populates_allowed_columns() -> None:
    field_name = "metadata.custom_score"
    registry = build_default_registry(collection_id=COLLECTION_ID)
    # Format the metadata column name by replacing dots with -> syntax
    formatted = field_name.replace(".", "->'") + "'"
    registry.extend_table_columns(SQLAAgentRun.__tablename__, [formatted])
    assert formatted.lower() in registry.get_table(SQLAAgentRun.__tablename__).allowed_columns


def test_json_field_info_to_expression() -> None:
    info = JsonFieldInfo(
        column="metadata_json",
        path=("detail", "score"),
        value_type="float",
        labels={},
    )
    assert json_field_info_to_expression(info) == "metadata_json->'detail'->'score'"


def test_multi_statement_query_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        parse_dql_query(
            "SELECT id FROM agent_runs; DROP TABLE agent_runs",
            registry=registry,
            collection_id=COLLECTION_ID,
        )


def test_update_statement_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        parse_dql_query(
            "UPDATE agent_runs SET name = 'x' WHERE id = '1'",
            registry=registry,
            collection_id=COLLECTION_ID,
        )


def test_drop_statement_rejected() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    with pytest.raises(DQLValidationError):
        parse_dql_query("DROP TABLE agent_runs", registry=registry, collection_id=COLLECTION_ID)


def test_build_sqla_query_scopes_to_collection() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="SELECT id FROM agent_runs",
            registry=registry,
        )
    )
    assert "collection_id" in clause.text
    assert "agent_runs.collection_id = :__dql_param_" in clause.text
    compiled = clause.compile()
    assert COLLECTION_ID in compiled.params.values()


def test_build_collection_sqla_query_wrapper_scopes_and_checks_permissions() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    mono_service = DummyMonoService(True)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=mono_service,  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id="test-collection",
            dql="SELECT id FROM agent_runs",
            registry=registry,
        )
    )
    assert "agent_runs.collection_id = :__dql_param_" in clause.text
    assert "collection_id" in clause.text
    compiled = clause.compile()
    assert COLLECTION_ID in compiled.params.values()


def test_build_collection_sqla_query_wrapper_denied() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    mono_service = DummyMonoService(False)  # type: ignore[arg-type]
    with pytest.raises(DQLValidationError):
        asyncio.run(
            build_collection_sqla_query(
                mono_service=mono_service,  # type: ignore[arg-type]
                user=TEST_USER,
                collection_id="test-collection",
                dql="SELECT id FROM agent_runs",
                registry=registry,
            )
        )


def test_build_collection_sqla_query_wrapper_requires_permission() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    mono_service = DummyMonoService(True)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=mono_service,  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id="test-collection",
            dql="SELECT id FROM agent_runs WHERE agent_runs.id = 'foo'",
            registry=registry,
        )
    )
    assert "agent_runs.id" in clause.text


def test_transcripts_query_scoped() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="SELECT id FROM transcripts",
            registry=registry,
        )
    )
    assert "transcripts.collection_id = :__dql_param_" in clause.text
    compiled = clause.compile()
    assert COLLECTION_ID in compiled.params.values()


def test_transcript_groups_query_scoped() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="SELECT id FROM transcript_groups",
            registry=registry,
        )
    )
    assert "transcript_groups.collection_id = :__dql_param_" in clause.text
    compiled = clause.compile()
    assert COLLECTION_ID in compiled.params.values()


def test_judge_results_query_scoped_via_agent_run_subquery() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="SELECT agent_run_id FROM judge_results",
            registry=registry,
        )
    )
    assert "agent_runs" in clause.text
    assert "collection_id = :__dql_param_" in clause.text
    compiled = clause.compile()
    assert COLLECTION_ID in compiled.params.values()


def test_union_query_allowed() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    clause = asyncio.run(
        build_collection_sqla_query(
            mono_service=DummyMonoService(True),  # type: ignore[arg-type]
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql=(
                "SELECT id FROM agent_runs WHERE name = 'alpha' "
                "UNION "
                "SELECT id FROM agent_runs WHERE name = 'beta'"
            ),
            registry=registry,
        )
    )
    sql_text = clause.text
    assert "UNION" in sql_text
    # Ensure both branches are collection scoped.
    assert sql_text.count("collection_id = :__dql_param_") >= 2


def test_get_query_limit_value_and_apply_limit_cap() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    expression = parse_dql_query(
        "SELECT id FROM agent_runs LIMIT 3", registry=registry, collection_id=COLLECTION_ID
    )
    # The expression should be a Select, not Query
    assert isinstance(expression, exp.Select)
    query_expression = cast(QueryExpression, expression)
    assert get_query_limit_value(query_expression) == 3

    apply_limit_cap(query_expression, 5)
    assert get_query_limit_value(query_expression) == 5
    rendered_sql = query_expression.sql(dialect="postgres", pretty=False)  # type: ignore[reportUnknownMemberType]
    assert rendered_sql.endswith("LIMIT 5")


def test_union_limit_cap() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    expression = parse_dql_query(
        "SELECT id FROM agent_runs UNION SELECT id FROM agent_runs LIMIT 9",
        registry=registry,
        collection_id=COLLECTION_ID,
    )
    assert isinstance(expression, exp.Union)
    query_expression = cast(QueryExpression, expression)
    assert get_query_limit_value(query_expression) == 9
    apply_limit_cap(query_expression, 4)
    assert get_query_limit_value(query_expression) == 4


def test_apply_limit_cap_requires_positive_limit() -> None:
    registry = build_default_registry(collection_id=COLLECTION_ID)
    expression = parse_dql_query(
        "SELECT id FROM agent_runs", registry=registry, collection_id=COLLECTION_ID
    )
    assert isinstance(expression, exp.Select)
    query_expression = cast(QueryExpression, expression)
    with pytest.raises(ValueError):
        apply_limit_cap(query_expression, 0)


class _ResultStub:
    def __init__(self, *, columns: tuple[str, ...] = (), rows: list[tuple[str, ...]] | None = None):
        self._columns = columns
        self._rows = rows or []
        self.closed = False

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def fetchall(self) -> list[tuple[str, ...]]:
        return list(self._rows)

    def close(self) -> None:
        self.closed = True


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, str] | None]] = []

    async def execute(
        self, statement: TextClause, params: dict[str, Any] | None = None
    ) -> _ResultStub:
        sql = getattr(statement, "text", str(statement))
        self.statements.append((sql, params))
        if sql.startswith("SET TRANSACTION READ ONLY"):
            return _ResultStub()
        if sql.startswith("SET LOCAL ROLE"):
            return _ResultStub()
        if sql.startswith("SELECT set_config"):
            return _ResultStub()
        if "FROM agent_runs" in sql:
            return _ResultStub(columns=("id",), rows=[("row-1",)])
        raise AssertionError(f"Unexpected SQL: {sql}")


class _DummyDB:
    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    @asynccontextmanager
    async def dql_session(self, collection_id: str):
        await self._session.execute(text("SET TRANSACTION READ ONLY"))
        await self._session.execute(text("SET LOCAL ROLE docent_dql_reader"))
        await self._session.execute(
            text(f"SELECT set_config('{DQL_COLLECTION_SETTING_KEY}', :collection_id, true)"),
            {"collection_id": collection_id},
        )
        yield self._session


@pytest.mark.asyncio
async def test_execute_dql_query_sets_read_only_rls_context() -> None:
    import docent_core.docent.services.dql as dql_service_module

    # Patch the permission check to allow access for this test
    # Must patch in the services.dql module where it's imported
    async def allow_access(mono_service, user, collection_id):  # type: ignore[override]
        pass

    original_ensure = dql_service_module.ensure_dql_collection_access
    dql_service_module.ensure_dql_collection_access = allow_access

    try:
        session = _RecordingSession()
        db = _DummyDB(session)
        dql_service = DQLService(db)  # type: ignore[arg-type]
        result = await dql_service.execute_query(
            user=TEST_USER,
            collection_id=COLLECTION_ID,
            dql="SELECT id FROM agent_runs",
            json_fields={},
        )
    finally:
        dql_service_module.ensure_dql_collection_access = original_ensure

    query_sql, query_params = next(
        (sql, params) for sql, params in session.statements if "FROM agent_runs" in sql
    )
    assert "FROM agent_runs" in query_sql
    assert "collection_id = :__dql_param_" in query_sql
    assert query_params is not None
    assert DEFAULT_DQL_MAX_ROWS + 1 in query_params.values()
    assert COLLECTION_ID in query_params.values()
    assert result.columns == ("id",)
    assert result.rows == [("row-1",)]
    assert result.applied_limit == DEFAULT_DQL_MAX_ROWS
