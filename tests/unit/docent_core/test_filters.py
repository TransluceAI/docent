from __future__ import annotations

from sqlalchemy.dialects import postgresql

from docent_core.docent.db.filters import FilterSQLContext, PrimitiveFilter
from docent_core.docent.db.schemas.tables import SQLAAgentRun


def _ensure_refinement_mapper_registered() -> None:
    from docent_core.docent.db.schemas.refinement import SQLARefinementAgentSession

    assert SQLARefinementAgentSession


def test_filter_sql_context_creates_join_for_rubric() -> None:
    rubric_id = "abcd1234-aaaa-bbbb-ccccddddffff"
    context = FilterSQLContext(SQLAAgentRun)

    join_spec = context.get_rubric_alias(rubric_id, ["label"])

    assert join_spec.alias is not None
    compiled = join_spec.onclause.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    sql = str(compiled)
    assert "rubric_value_0" in sql
    assert "agent_runs.id" in sql


def test_filter_sql_context_missing_prefix_creates_new_join() -> None:
    rubric_id = "missing-id"
    context = FilterSQLContext(SQLAAgentRun)
    join_spec = context.get_rubric_alias(rubric_id, ["label"])
    sql = str(
        join_spec.onclause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "rubric_value_0" in sql


def test_filter_sql_context_ambiguous_prefix_raises() -> None:
    rubric_id = "id-one"
    context = FilterSQLContext(SQLAAgentRun)
    first_alias = context.get_rubric_alias(rubric_id, ["label"])
    second_alias = context.get_rubric_alias(rubric_id, ["label"])
    assert first_alias.alias is second_alias.alias


def test_primitive_filter_generates_rubric_clause() -> None:
    rubric_id = "abcd1234-aaaa-bbbb-ccccddddffff"
    context = FilterSQLContext(SQLAAgentRun)
    filter_obj = PrimitiveFilter(
        key_path=["rubric", rubric_id, "label"],
        value="match",
        op="==",
    )

    clause = filter_obj.to_sqla_where_clause(SQLAAgentRun, context=context)
    assert clause is not None
    compiled = clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    sql = str(compiled)
    assert "rubric_value_0" in sql
    assert "match" in sql
    assert len(context.required_joins()) == 1


def test_filter_sql_context_creates_join_for_tag() -> None:
    _ensure_refinement_mapper_registered()
    context = FilterSQLContext(SQLAAgentRun)

    join_spec = context.get_tag_alias()

    assert join_spec.alias is not None
    compiled = join_spec.onclause.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    sql = str(compiled)
    assert "tag_filter" in sql


def test_primitive_filter_generates_tag_clause() -> None:
    _ensure_refinement_mapper_registered()
    context = FilterSQLContext(SQLAAgentRun)
    filter_obj = PrimitiveFilter(
        key_path=["tag"],
        value="priority",
        op="==",
    )

    clause = filter_obj.to_sqla_where_clause(SQLAAgentRun, context=context)
    assert clause is not None
    compiled = clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    sql = str(compiled)
    assert "tag_filter" in sql
    assert "priority" in sql
    assert len(context.required_joins()) == 1
