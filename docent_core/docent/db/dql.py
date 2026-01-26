"""Helpers for parsing and validating Docent Query Language against allowed tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    TypeAlias,
    TypeVar,
    cast,
)

import sqlglot
from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.schema import Table
from sqlalchemy.sql.selectable import FromClause
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import (
    Scope,
    build_scope,
    find_all_in_scope,  # type: ignore[reportUnknownVariableType]
)

from docent._log_util import get_logger
from docent.data_models.agent_run import FilterableFieldType
from docent_core.docent.db.schemas.auth_models import Permission, ResourceType, User
from docent_core.docent.db.schemas.label import SQLALabel, SQLALabelSet, SQLATag
from docent_core.docent.db.schemas.result_tables import SQLAResult, SQLAResultSet
from docent_core.docent.db.schemas.rubric import (
    SQLAJudgeResult,
    SQLAJudgeResultCentroid,
    SQLARubricCentroid,
)
from docent_core.docent.db.schemas.tables import (
    SQLAAgentRun,
    SQLATranscript,
    SQLATranscriptGroup,
)

if TYPE_CHECKING:
    from docent_core.docent.services.monoservice import MonoService

SqlGlotExpression = exp.Expression
SqlGlotColumn = exp.Column
TExpr = TypeVar("TExpr", bound=SqlGlotExpression)
QueryExpression = exp.Query | exp.SetOperation

__all__ = [
    "AllowedTable",
    "ColumnReference",
    "DQLParseError",
    "DQLRegistry",
    "DQL_COLLECTION_SETTING_KEY",
    "DQLValidationError",
    "DQLExecutionError",
    "apply_limit_cap",
    "ensure_dql_collection_access",
    "get_query_limit_value",
    "SelectedColumn",
    "JsonFieldInfo",
    "json_field_info_to_expression",
    "parameterize_expression",
    "build_default_registry",
    "build_collection_sqla_query",
    "extract_selected_columns",
    "get_selected_columns",
    "parse_dql_query",
    "QueryExpression",
]


logger = get_logger(__name__)

DQL_COLLECTION_SETTING_KEY = "docent.collection_id"


class DQLParseError(ValueError):
    """Raised when a Docent Query Language string cannot be parsed."""


class DQLValidationError(ValueError):
    """Raised when a Docent Query Language string references disallowed resources."""


class DQLExecutionError(ValueError):
    """Raised when execution of a Docent Query Language statement fails."""


@dataclass(frozen=True)
class AllowedTable:
    """Captures the whitelist metadata for a table that DQL callers may reference."""

    name: str
    table: Table | FromClause
    allowed_columns: frozenset[str]
    collection_predicate_factory: "CollectionPredicateFactory | None" = None
    aliases: frozenset[str] = field(default_factory=lambda: frozenset())
    column_aliases: Mapping[str, str] = field(default_factory=lambda: {})
    json_field_paths: frozenset[str] = field(default_factory=lambda: frozenset())


@dataclass(frozen=True)
class ColumnReference:
    """Track table-qualified columns so downstream tooling can reason about provenance."""

    table: str | None
    column: str


@dataclass(frozen=True)
class SelectedColumn:
    """Describe SELECT outputs and their sources so clients can build typed result schemas."""

    output_name: str
    expression_sql: str
    source_columns: tuple[ColumnReference, ...]


@dataclass(frozen=True)
class JsonFieldInfo:
    column: str
    path: tuple[str, ...] = field(default_factory=tuple)
    value_type: FilterableFieldType | None = None
    labels: Mapping[str, str] = field(default_factory=dict)  # type: ignore[reportUnknownVariableType]


@dataclass(frozen=True)
class _ParameterBinding:
    value: Any
    pg_type: str | None = None


CollectionPredicateFactory = Callable[[str, str], SqlGlotExpression]
QueryParameters: TypeAlias = dict[str, Any]
SqlAndParameters: TypeAlias = tuple[str, QueryParameters]

ALLOWED_EXPRESSION_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Subquery,
    exp.Table,
    exp.TableAlias,
    exp.From,
    exp.Where,
    exp.With,
    exp.CTE,
    exp.Order,
    exp.Limit,
    exp.Offset,
    exp.Distinct,
    exp.Join,
    exp.Alias,
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Boolean,
    exp.And,
    exp.Or,
    exp.Not,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Is,
    exp.Null,
    exp.If,
    exp.In,
    exp.Exists,
    exp.Like,
    exp.ILike,
    exp.Between,
    exp.Paren,
    exp.Neg,
    exp.Cast,
    exp.Group,
    exp.Having,
    exp.Case,
    exp.When,
    exp.Ordered,
    # Aggregation functions
    exp.Count,
    exp.Avg,
    exp.Max,
    exp.Min,
    exp.Sum,
    exp.Stddev,
    exp.StddevPop,
    exp.StddevSamp,
    exp.Variance,
    exp.Var,
    exp.CovarPop,
    exp.CovarSamp,
    exp.ArrayAgg,
    exp.Median,
    exp.PercentileCont,
    exp.PercentileDisc,
    exp.GroupConcat,
    exp.WithinGroup,
    exp.Filter,
    # String aggregation functions
    exp.Concat,
    exp.ConcatWs,
    exp.JSONArrayAgg,
    exp.JSONObjectAgg,
    exp.JSONBObjectAgg,
    # Window functions
    exp.Window,
    exp.RowNumber,
    exp.Rank,
    exp.DenseRank,
    exp.Ntile,
    exp.Lag,
    exp.Lead,
    exp.FirstValue,
    exp.LastValue,
    exp.NthValue,
    exp.PercentRank,
    exp.CumeDist,
    # Set operations
    exp.Union,
    exp.Intersect,
    exp.Except,
    # String functions
    exp.Substring,
    exp.Left,
    exp.Right,
    exp.Length,
    exp.Upper,
    exp.Lower,
    exp.Initcap,
    exp.Trim,
    exp.Replace,
    exp.SplitPart,
    exp.StrPosition,
    # Date/Time functions
    exp.CurrentDate,
    exp.CurrentTime,
    exp.CurrentTimestamp,
    exp.Extract,
    exp.DateTrunc,
    exp.TimestampTrunc,
    exp.DatetimeTrunc,
    exp.TimeTrunc,
    exp.ToChar,
    exp.Interval,
    exp.AtTimeZone,
    exp.FromTimeZone,
    exp.ConvertTimezone,
    # Date extraction functions
    exp.Year,
    exp.Month,
    exp.Day,
    exp.DayOfMonth,
    exp.DayOfWeek,
    exp.DayOfWeekIso,
    exp.DayOfYear,
    exp.Week,
    exp.WeekOfYear,
    exp.Quarter,
    # Date arithmetic functions
    exp.DateAdd,
    exp.DateSub,
    exp.DateDiff,
    exp.DatetimeAdd,
    exp.DatetimeSub,
    exp.DatetimeDiff,
    exp.TimeAdd,
    exp.TimeSub,
    exp.TimeDiff,
    exp.TimestampAdd,
    exp.TimestampSub,
    exp.TimestampDiff,
    exp.MonthsBetween,
    exp.AddMonths,
    # Date construction functions
    exp.DateFromParts,
    exp.TimeFromParts,
    exp.TimestampFromParts,
    exp.DateFromUnixDate,
    exp.UnixDate,
    exp.UnixSeconds,
    exp.LastDay,
    # Date conversion functions
    exp.Date,
    exp.Time,
    exp.Timestamp,
    exp.Datetime,
    exp.StrToDate,
    exp.StrToTime,
    exp.DateToDateStr,
    exp.TimeToStr,
    exp.TimeToTimeStr,
    exp.UnixToTime,
    exp.UnixToTimeStr,
    exp.ParseDatetime,
    exp.ParseTime,
    exp.FromISO8601Timestamp,
    # Mathematical functions
    exp.Abs,
    exp.Sign,
    exp.Sqrt,
    exp.Cbrt,
    exp.Log,
    exp.Ln,
    exp.Exp,
    exp.Pow,
    exp.Rand,
    exp.Greatest,
    exp.Least,
    # NULL handling functions
    exp.Coalesce,
    exp.Nullif,
    # JSON advanced operators
    exp.JSONBContains,
    exp.JSONBExists,
    exp.JSONBExtract,
    exp.JSONBExtractScalar,
    exp.JSONExtract,
    exp.JSONExtractScalar,
    exp.JSONArray,
    exp.JSONPath,
    exp.JSONPathRoot,
    exp.JSONPathKey,
    exp.JSONPathSubscript,
    exp.JSONPathSelector,
    exp.JSONPathFilter,
    # JSON containment operators
    exp.ArrayContainsAll,
    exp.ArrayContains,
    exp.JSONArrayContains,
    # Pattern matching
    exp.SimilarTo,
    exp.RegexpLike,
    exp.RegexpReplace,
    # Array functions
    exp.ArraySize,
    exp.ArrayConcat,
    exp.Unnest,
    # Data type functions
    exp.DataType,
    exp.Lambda,
    # Arithmetic operators
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Mod,
    exp.Pow,
    exp.Floor,
    exp.Ceil,
    exp.Round,
    # Anonymous functions are validated separately via ALLOWED_ANONYMOUS_FUNCTIONS
    exp.Anonymous,
)

# Whitelist of anonymous function names (functions sqlglot doesn't have explicit types for)
# These are checked case-insensitively
ALLOWED_ANONYMOUS_FUNCTIONS: frozenset[str] = frozenset(
    {
        # Ordered-set aggregate functions
        "mode",
        # String aggregation
        "string_agg",
        # JSONB construction
        "jsonb_build_object",
    }
)


def _resolve_column_name(table: AllowedTable, column_name: str, column_sql: str) -> str:
    """Return the canonical column name, enforcing the table's approved column list."""

    column_lower = column_name.lower()
    if column_lower in table.allowed_columns:
        return column_lower

    alias_target = table.column_aliases.get(column_lower)
    if alias_target and alias_target in table.allowed_columns:
        return alias_target

    raise DQLValidationError(
        f"Column '{column_sql}' is not a valid column for table '{table.name}'."
    )


def _columns_for(table: Table | FromClause) -> tuple[str, ...]:
    """Expose the SQLAlchemy column keys used to seed the registry for a table."""

    return tuple(column.key for column in table.c)  # type: ignore[attr-defined]


def _column_equals_collection(column_name: str) -> CollectionPredicateFactory:
    """Build a predicate factory that scopes a table to a collection identifier."""

    def builder(table_alias: str, collection_id: str) -> SqlGlotExpression:
        return exp.EQ(
            this=exp.column(column_name, table=table_alias),
            expression=exp.Literal.string(collection_id),  # type: ignore[reportUnknownMemberType]
        )

    return builder


def _escape_json_path_segment(segment: str) -> str:
    return segment.replace("'", "''")


def _format_json_column_expression(column: str, path: Sequence[str]) -> str:
    if not path:
        return column
    return column + "".join(f"->'{_escape_json_path_segment(segment)}'" for segment in path)


def json_field_info_to_expression(info: JsonFieldInfo) -> str:
    return _format_json_column_expression(info.column, info.path)


def _judge_result_collection_predicate(table_alias: str, collection_id: str) -> SqlGlotExpression:
    """Filter judge results by ensuring their linked agent run belongs to the collection."""

    subquery = (
        exp.select(exp.Literal.string("1"))  # type: ignore[reportUnknownMemberType]
        .from_(SQLAAgentRun.__tablename__)  # type: ignore[reportUnknownMemberType]
        .where(  # type: ignore[reportUnknownMemberType]
            exp.and_(  # type: ignore[reportUnknownMemberType]
                exp.EQ(
                    this=exp.column("collection_id", table=SQLAAgentRun.__tablename__),
                    expression=exp.Literal.string(collection_id),  # type: ignore[reportUnknownMemberType]
                ),
                exp.EQ(
                    this=exp.column("id", table=SQLAAgentRun.__tablename__),
                    expression=exp.column("agent_run_id", table=table_alias),
                ),
            )
        )
    )
    return exp.Exists(this=subquery)


def _label_collection_predicate(table_alias: str, collection_id: str) -> SqlGlotExpression:
    """Filter labels by ensuring their linked agent run belongs to the collection."""

    subquery = (
        exp.select(exp.Literal.string("1"))  # type: ignore[reportUnknownMemberType]
        .from_(SQLAAgentRun.__tablename__)  # type: ignore[reportUnknownMemberType]
        .where(  # type: ignore[reportUnknownMemberType]
            exp.and_(  # type: ignore[reportUnknownMemberType]
                exp.EQ(
                    this=exp.column("collection_id", table=SQLAAgentRun.__tablename__),
                    expression=exp.Literal.string(collection_id),  # type: ignore[reportUnknownMemberType]
                ),
                exp.EQ(
                    this=exp.column("id", table=SQLAAgentRun.__tablename__),
                    expression=exp.column("agent_run_id", table=table_alias),
                ),
            )
        )
    )
    return exp.Exists(this=subquery)


def _judge_result_centroid_collection_predicate(
    table_alias: str, collection_id: str
) -> SqlGlotExpression:
    """Filter judge result centroids by ensuring their linked judge result belongs to the collection."""

    subquery = (
        exp.select(exp.Literal.string("1"))  # type: ignore[reportUnknownMemberType]
        .from_(SQLAJudgeResult.__tablename__)  # type: ignore[reportUnknownMemberType]
        .join(  # type: ignore[reportUnknownMemberType]
            SQLAAgentRun.__tablename__,
            on=exp.EQ(
                this=exp.column("id", table=SQLAAgentRun.__tablename__),
                expression=exp.column("agent_run_id", table=SQLAJudgeResult.__tablename__),
            ),
        )
        .where(  # type: ignore[reportUnknownMemberType]
            exp.and_(  # type: ignore[reportUnknownMemberType]
                exp.EQ(
                    this=exp.column("collection_id", table=SQLAAgentRun.__tablename__),
                    expression=exp.Literal.string(collection_id),  # type: ignore[reportUnknownMemberType]
                ),
                exp.EQ(
                    this=exp.column("id", table=SQLAJudgeResult.__tablename__),
                    expression=exp.column("judge_result_id", table=table_alias),
                ),
            )
        )
    )
    return exp.Exists(this=subquery)


def _result_collection_predicate(table_alias: str, collection_id: str) -> SqlGlotExpression:
    """Filter results by ensuring their linked result_set belongs to the collection."""

    subquery = (
        exp.select(exp.Literal.string("1"))  # type: ignore[reportUnknownMemberType]
        .from_(SQLAResultSet.__tablename__)  # type: ignore[reportUnknownMemberType]
        .where(  # type: ignore[reportUnknownMemberType]
            exp.and_(  # type: ignore[reportUnknownMemberType]
                exp.EQ(
                    this=exp.column("collection_id", table=SQLAResultSet.__tablename__),
                    expression=exp.Literal.string(collection_id),  # type: ignore[reportUnknownMemberType]
                ),
                exp.EQ(
                    this=exp.column("id", table=SQLAResultSet.__tablename__),
                    expression=exp.column("result_set_id", table=table_alias),
                ),
            )
        )
    )
    return exp.Exists(this=subquery)


class DQLRegistry:
    """Keeps track of which database tables and columns DQL callers may access."""

    def __init__(self) -> None:
        """Initialize the registry storage for allowed tables and their aliases."""

        self._tables: dict[str, AllowedTable] = {}
        self._table_aliases: dict[str, str] = {}

    def register_table(
        self,
        *,
        name: str,
        table: Table | FromClause,
        allowed_columns: Iterable[str],
        collection_predicate_factory: CollectionPredicateFactory | None = None,
        aliases: Iterable[str] | None = None,
        column_aliases: Mapping[str, str] | None = None,
        json_field_paths: Iterable[str] | None = None,
    ) -> None:
        """Register a table and validate its aliases so DQL enforcement stays consistent."""

        table_key = name.lower()
        if table_key in self._tables or table_key in self._table_aliases:
            raise ValueError(f"Table '{name}' is already registered.")

        table_columns: dict[str, str] = {col.lower(): col for col in allowed_columns}
        if not table_columns:
            raise ValueError(f"Table '{name}' must expose at least one column.")

        alias_set: frozenset[str] = frozenset(alias.lower() for alias in (aliases or ()))
        for alias in alias_set:
            if alias in self._tables or alias in self._table_aliases:
                raise ValueError(f"Table alias '{alias}' is already registered.")
            if alias == table_key:
                raise ValueError("Table alias cannot be the same as the table name.")

        column_alias_map: dict[str, str] = {}
        if column_aliases:
            for alias_name, target_name in column_aliases.items():
                alias_lower = alias_name.lower()
                target_lower = target_name.lower()
                if alias_lower in table_columns:
                    raise ValueError(
                        f"Column alias '{alias_name}' conflicts with existing column on table '{name}'."
                    )
                column_alias_map[alias_lower] = target_lower

        json_paths: tuple[str, ...] = tuple(json_field_paths or ())
        for path in json_paths:
            table_columns[path.lower()] = path

        self._tables[table_key] = AllowedTable(
            name=table_key,
            table=table,
            allowed_columns=frozenset(table_columns.keys()),
            collection_predicate_factory=collection_predicate_factory,
            aliases=alias_set,
            column_aliases=column_alias_map,
            json_field_paths=frozenset(json_paths),
        )

        for alias in alias_set:
            self._table_aliases[alias] = table_key

    def get_table(self, name: str) -> AllowedTable:
        """Return the AllowedTable for a name or alias, raising when the table is disallowed."""

        key = name.lower()
        if key in self._tables:
            return self._tables[key]
        alias_target = self._table_aliases.get(key)
        if alias_target and alias_target in self._tables:
            return self._tables[alias_target]
        raise DQLValidationError(f"Table '{name}' is not a valid table for Docent Query Language.")

    def iter_tables(self) -> tuple[AllowedTable, ...]:
        """Expose the registered tables so callers can derive metadata snapshots."""

        return tuple(self._tables.values())

    def extend_table_columns(self, name: str, columns: Iterable[str]) -> None:
        """Allow additional columns (typically dynamic JSON fields) on an existing table."""

        table_key = name.lower()
        if table_key not in self._tables:
            raise DQLValidationError(
                f"Table '{name}' is not a valid table for Docent Query Language."
            )

        allowed_table = self._tables[table_key]
        new_columns: list[str] = list(columns)
        updated_columns = allowed_table.allowed_columns.union(
            {column.lower() for column in new_columns}
        )
        updated_json_paths = allowed_table.json_field_paths.union(new_columns)

        self._tables[table_key] = AllowedTable(
            name=allowed_table.name,
            table=allowed_table.table,
            allowed_columns=updated_columns,
            collection_predicate_factory=allowed_table.collection_predicate_factory,
            aliases=allowed_table.aliases,
            column_aliases=allowed_table.column_aliases,
            json_field_paths=frozenset(updated_json_paths),
        )


def build_default_registry(
    *,
    collection_id: str | None = None,
    json_fields: Mapping[str, Iterable[JsonFieldInfo]] | None = None,
    allow_without_collection: bool = False,
) -> DQLRegistry:
    """Seed a registry with Docent's built-in tables.

    Args:
        collection_id: Identifier for the collection whose data will be queried.
        json_fields: Optional mapping of table name to discovered JSON field infos that should
            be whitelisted alongside the base columns.
        allow_without_collection: Internal/testing escape hatch; when False and
            `collection_id` is missing, raises to prevent running DQL without a scope.
    """

    if collection_id is None and not allow_without_collection:
        raise ValueError(
            "collection_id is required when building the DQL registry. "
            "Pass allow_without_collection=True only in trusted test scenarios."
        )

    registry = DQLRegistry()
    logger.debug(
        "Building DQL registry for collection_id=%s allow_without_collection=%s json_field_tables=%s",
        collection_id,
        allow_without_collection,
        sorted(json_fields.keys()) if json_fields else (),
    )

    registry.register_table(
        name=SQLAAgentRun.__tablename__,
        table=SQLAAgentRun.__table__,
        allowed_columns=_columns_for(SQLAAgentRun.__table__),
        collection_predicate_factory=_column_equals_collection("collection_id"),
        column_aliases={"metadata": "metadata_json"},
    )
    registry.register_table(
        name=SQLATranscript.__tablename__,
        table=SQLATranscript.__table__,
        allowed_columns=_columns_for(SQLATranscript.__table__),
        collection_predicate_factory=_column_equals_collection("collection_id"),
    )
    registry.register_table(
        name=SQLATranscriptGroup.__tablename__,
        table=SQLATranscriptGroup.__table__,
        allowed_columns=_columns_for(SQLATranscriptGroup.__table__),
        collection_predicate_factory=_column_equals_collection("collection_id"),
    )
    registry.register_table(
        name=SQLAJudgeResult.__tablename__,
        table=SQLAJudgeResult.__table__,
        allowed_columns=_columns_for(SQLAJudgeResult.__table__),
        collection_predicate_factory=_judge_result_collection_predicate,
    )
    registry.register_table(
        name=SQLALabel.__tablename__,
        table=SQLALabel.__table__,
        allowed_columns=_columns_for(SQLALabel.__table__),
        collection_predicate_factory=_label_collection_predicate,
    )
    registry.register_table(
        name=SQLALabelSet.__tablename__,
        table=SQLALabelSet.__table__,
        allowed_columns=_columns_for(SQLALabelSet.__table__),
        collection_predicate_factory=_column_equals_collection("collection_id"),
    )
    registry.register_table(
        name=SQLATag.__tablename__,
        table=SQLATag.__table__,
        allowed_columns=_columns_for(SQLATag.__table__),
        collection_predicate_factory=_column_equals_collection("collection_id"),
    )
    registry.register_table(
        name=SQLARubricCentroid.__tablename__,
        table=SQLARubricCentroid.__table__,
        allowed_columns=_columns_for(SQLARubricCentroid.__table__),
        collection_predicate_factory=_column_equals_collection("collection_id"),
    )
    registry.register_table(
        name=SQLAJudgeResultCentroid.__tablename__,
        table=SQLAJudgeResultCentroid.__table__,
        allowed_columns=_columns_for(SQLAJudgeResultCentroid.__table__),
        collection_predicate_factory=_judge_result_centroid_collection_predicate,
    )
    registry.register_table(
        name=SQLAResult.__tablename__,
        table=SQLAResult.__table__,
        allowed_columns=_columns_for(SQLAResult.__table__),
        collection_predicate_factory=_result_collection_predicate,
    )

    if json_fields:
        for table_name, infos in json_fields.items():
            expressions: set[str] = set()
            for info in infos:
                if not info.path:
                    continue
                expressions.add(json_field_info_to_expression(info))
            if expressions:
                registry.extend_table_columns(table_name, sorted(expressions))

    logger.debug(
        "Built DQL registry for collection_id=%s with tables=%s",
        collection_id,
        tuple(sorted(table.name for table in registry.iter_tables())),
    )
    return registry


def _parse_sql_statements(sql: str) -> list[SqlGlotExpression]:
    """Parse SQL into expressions, ignoring empty statements introduced by the parser."""

    parsed = sqlglot.parse(sql, read="postgres")  # type: ignore[reportUnknownMemberType]
    results: list[SqlGlotExpression] = []
    for stmt in parsed:
        if stmt is None:
            continue
        assert isinstance(stmt, exp.Expression)
        results.append(stmt)
    return results


def _render_sql(expression: SqlGlotExpression, sql_dialect: str) -> str:
    """Serialize a sqlglot expression so we can hand it to SQLAlchemy unchanged."""

    rendered = expression.sql(dialect=sql_dialect, pretty=False)  # type: ignore[reportUnknownMemberType]
    return str(rendered)


def _literal_to_binding(literal: exp.Literal) -> _ParameterBinding:
    value = literal.this
    if literal.is_string:
        return _ParameterBinding(value=value, pg_type=None)
    if literal.is_number:
        text_value = str(value)
        try:
            if any(sep in text_value.lower() for sep in (".", "e")):
                return _ParameterBinding(value=float(text_value), pg_type="numeric")
            return _ParameterBinding(value=int(text_value), pg_type="integer")
        except ValueError:
            try:
                return _ParameterBinding(value=float(text_value), pg_type="numeric")
            except ValueError:
                return _ParameterBinding(value=text_value, pg_type=None)
    return _ParameterBinding(value=value, pg_type=None)


def parameterize_expression(
    expression: SqlGlotExpression,
    sql_dialect: str,
) -> SqlAndParameters:
    cloned = expression.copy()
    params: QueryParameters = {}
    cast_hints: dict[str, str] = {}

    literals: list[exp.Literal] = list(cloned.find_all(exp.Literal))
    param_index = 0
    for literal in literals:
        if literal.find_ancestor(exp.Interval) is not None:
            # sqlglot renders interval values with embedded quoting, so replacing the
            # literal with a bind parameter would produce invalid syntax like
            # INTERVAL '__dql_param_1 DAY'. Leaving interval literals in place keeps
            # the generated SQL valid while the surrounding AST validation enforces
            # allowed constructs.
            continue
        param_index += 1
        param_name = f"__dql_param_{param_index}"
        binding = _literal_to_binding(literal)
        params[param_name] = binding.value
        if binding.pg_type is not None:
            cast_hints[param_name] = binding.pg_type
        literal.replace(exp.Parameter(this=param_name))

    sql = _render_sql(cloned, sql_dialect)
    if params:
        # Sort by name length descending to avoid prefix collisions
        # (e.g., $__dql_param_1 matching prefix of $__dql_param_16)
        for name in sorted(params.keys(), key=len, reverse=True):
            cast_type = cast_hints.get(name)
            if cast_type is not None:
                replacement = f"(:{name})::{cast_type}"
            else:
                replacement = f":{name}"
            sql = sql.replace(f"${name}", replacement)
    return sql, params


def _iter_columns(expression: SqlGlotExpression) -> Iterator[SqlGlotColumn]:
    """Walk an expression and yield all column nodes for downstream analysis."""

    for column in expression.find_all(exp.Column):
        assert isinstance(column, exp.Column)
        yield column


def _iter_scope_children(scope: Scope) -> Iterator[Scope]:
    """Iterate child scopes so validation can recurse through the query tree."""

    for attribute in ("table_scopes", "subquery_scopes", "cte_scopes", "union_scopes"):
        collection = getattr(scope, attribute, None)
        if not collection:
            continue
        for child in collection:
            if isinstance(child, Scope):
                yield child


def _apply_collection_filter(
    scope: Scope,
    table_alias: str,
    predicate_factory: CollectionPredicateFactory,
    collection_id: str,
) -> None:
    """Inject a collection predicate onto a scope so every table access is collection scoped."""

    target = scope.expression
    if isinstance(target, exp.Subquery):
        target = target.this
    elif isinstance(target, exp.CTE):
        cte_body = target.this
        if isinstance(cte_body, exp.Subquery):
            target = cte_body.this
        else:
            target = cte_body
    if not isinstance(target, exp.Select):
        return

    applied_aliases: set[str] = getattr(scope, "_collection_filter_aliases", set())
    if table_alias in applied_aliases:
        return
    applied_aliases.add(table_alias)
    setattr(scope, "_collection_filter_aliases", applied_aliases)

    predicate = predicate_factory(table_alias, collection_id)
    existing_where = cast(exp.Where | None, target.args.get("where"))
    if existing_where is not None:
        combined = exp.and_(existing_where.this, predicate)  # type: ignore[reportUnknownMemberType]
        target.set("where", exp.Where(this=combined))
    else:
        target.set("where", exp.Where(this=predicate))
    logger.debug(
        "Applied collection filter to alias='%s' for collection_id=%s",
        table_alias,
        collection_id,
    )


def _apply_expression_sugar(expression: SqlGlotExpression) -> None:
    """Rewrite convenient-but-invalid constructs into safe SQL that DQL allows."""

    for count in expression.find_all(exp.Count):
        this_arg = count.args.get("this")
        expressions_arg = count.args.get("expressions")
        has_argument = this_arg is not None or bool(expressions_arg)
        if has_argument:
            continue
        # COUNT() is rewritten to COUNT(1) so users can avoid the '*' DQL forbids.
        count.set("this", exp.Literal.number(1))  # type: ignore[reportUnknownMemberType]


async def ensure_dql_collection_access(
    *,
    mono_service: MonoService,
    user: User,
    collection_id: str,
) -> None:
    """Verify that the user can read the collection before exposing any DQL-powered data."""

    logger.debug(
        "Checking DQL collection access for user_id=%s collection_id=%s",
        user.id,
        collection_id,
    )
    allowed = await mono_service.has_permission(
        user=user,
        resource_type=ResourceType.COLLECTION,
        resource_id=collection_id,
        permission=Permission.READ,
    )
    if not allowed:
        logger.warning(
            "DQL collection access denied for user_id=%s collection_id=%s",
            user.id,
            collection_id,
        )
        raise DQLValidationError(
            f"Permission denied for user {user.id} on collection {collection_id}"
        )
    logger.debug(
        "DQL collection access granted for user_id=%s collection_id=%s",
        user.id,
        collection_id,
    )


def parse_dql_query(
    dql: str,
    *,
    registry: DQLRegistry,
    collection_id: str,
) -> SqlGlotExpression:
    """Parse and validate a DQL SELECT statement against the registry and optional collection."""

    registry = registry or build_default_registry(
        collection_id=collection_id,
        allow_without_collection=collection_id is None,
    )
    stripped = dql.strip()
    if not stripped:
        raise DQLParseError("DQL query cannot be empty.")

    logger.debug("Parsing DQL query for collection_id=%s: %s", collection_id, stripped)
    try:
        statements: list[SqlGlotExpression] = _parse_sql_statements(stripped)
    except ParseError as exc:
        raise DQLParseError(str(exc)) from exc

    if len(statements) != 1:
        raise DQLValidationError("Only a single SELECT statement is permitted.")

    expression = statements[0]
    _apply_expression_sugar(expression)
    if not isinstance(expression, (exp.Query, exp.SetOperation)):
        raise DQLValidationError("Only SELECT-style queries are permitted.")

    query_expression: QueryExpression = expression
    _ensure_select_only(expression)
    _ensure_allowed_expressions(expression)
    _validate_query_expression(expression, registry, collection_id)
    table_names: list[str] = sorted({table.name for table in expression.find_all(exp.Table)})
    logger.debug(
        "Validated DQL query for collection_id=%s tables=%s limit=%s",
        collection_id,
        table_names,
        get_query_limit_value(query_expression),
    )
    return expression


def build_sqla_query(
    dql: str,
    *,
    registry: DQLRegistry,
    collection_id: str,
    sql_dialect: str = "postgres",
) -> TextClause:
    """Wrap the validated DQL in a SQLAlchemy text clause so callers can execute it safely."""

    expression = parse_dql_query(dql, registry=registry, collection_id=collection_id)
    sql, params = parameterize_expression(expression, sql_dialect)
    logger.debug("Compiled DQL query SQL: %s", sql)
    if params:
        logger.debug("DQL query parameters: %s", params)
    clause = text(sql)
    if params:
        clause = clause.bindparams(**params)
    return clause


async def build_collection_sqla_query(
    *,
    mono_service: MonoService,
    user: User,
    collection_id: str,
    dql: str,
    registry: DQLRegistry | None = None,
    sql_dialect: str = "postgres",
) -> TextClause:
    """Resolve collection-specific metadata and build a query only after permission checks."""

    logger.debug(
        "Building collection-scoped DQL query for user_id=%s collection_id=%s",
        user.id,
        collection_id,
    )
    await ensure_dql_collection_access(
        mono_service=mono_service,
        user=user,
        collection_id=collection_id,
    )
    effective_registry = registry
    if effective_registry is None:
        json_fields = await mono_service.get_json_metadata_fields_map(collection_id)
        effective_registry = build_default_registry(
            collection_id=collection_id,
            json_fields=json_fields,
        )

    return build_sqla_query(
        dql,
        registry=effective_registry,
        collection_id=collection_id,
        sql_dialect=sql_dialect,
    )


def get_selected_columns(
    dql: str,
    *,
    registry: DQLRegistry,
    collection_id: str,
    sql_dialect: str = "postgres",
) -> list[SelectedColumn]:
    """Return the projected columns for a DQL query so callers can build safe schemas."""

    expression = parse_dql_query(dql, registry=registry, collection_id=collection_id)
    return extract_selected_columns(expression, sql_dialect=sql_dialect)


def _iter_query_sources(query: SqlGlotExpression) -> list[SqlGlotExpression]:
    sources: list[SqlGlotExpression] = []

    def extend_from_clause(
        from_clause: SqlGlotExpression | Sequence[SqlGlotExpression] | None,
    ) -> None:
        if from_clause is None:
            return
        if isinstance(from_clause, exp.From):
            expressions = list(from_clause.expressions or [])
            if expressions:
                sources.extend(expressions)
            else:
                # sqlglot stores single-table FROMs in .this (expressions may be empty).
                from_target = from_clause.this
                if from_target is not None:
                    sources.append(from_target)
            return
        if isinstance(from_clause, Sequence):
            sources.extend(list(from_clause))
            return
        sources.append(from_clause)

    def extend_joins(join_clause: Sequence[SqlGlotExpression] | None) -> None:
        for join in join_clause or []:
            if isinstance(join, exp.Join):
                join_source = join.this
                if join_source is not None:
                    sources.append(join_source)

    from_expr = query.args.get("from")
    joins = cast(Sequence[SqlGlotExpression] | None, query.args.get("joins"))
    extend_from_clause(from_expr)
    extend_joins(joins)

    if not sources and isinstance(query, exp.Query):
        select_node = query.args.get("this")
        if isinstance(select_node, exp.Select):
            extend_from_clause(select_node.args.get("from"))
            extend_joins(cast(Sequence[SqlGlotExpression] | None, select_node.args.get("joins")))
    return sources


def _get_alias_name(expression: SqlGlotExpression) -> str | None:
    alias = expression.args.get("alias")
    if isinstance(alias, exp.TableAlias):
        alias_expr = alias.this
        if isinstance(alias_expr, exp.Identifier):
            return alias_expr.name
        if isinstance(alias_expr, exp.Literal):
            return str(alias_expr.this)
    return None


def _build_query_alias_map(
    query: SqlGlotExpression,
    cte_names: frozenset[str],
) -> tuple[dict[str, str], str | None]:
    alias_map: dict[str, str] = {}
    source_targets: list[str] = []
    for source in _iter_query_sources(query):
        if isinstance(source, exp.Table):
            name = source.name
            alias = _get_alias_name(source) or source.alias_or_name or name
            target = name
            if name.lower() in cte_names:
                target = name
            alias_map[alias.lower()] = target.lower()
            alias_map.setdefault(name.lower(), target.lower())
            source_targets.append(target.lower())
            continue
        if isinstance(source, exp.Subquery):
            alias = _get_alias_name(source) or source.alias_or_name
            if alias:
                alias_map[alias.lower()] = alias.lower()
                source_targets.append(alias.lower())

    default_table = source_targets[0] if len(set(source_targets)) == 1 else None
    return alias_map, default_table


def _resolve_column_references(
    column: SqlGlotColumn,
    *,
    alias_map: Mapping[str, str],
    default_table: str | None,
    cte_names: frozenset[str],
    resolve_cte: Callable[[str], Mapping[str, tuple[ColumnReference, ...]]],
) -> tuple[ColumnReference, ...]:
    column_table = cast(str | None, column.table)
    if column_table == "":
        column_table = None
    if column_table is None:
        column_table = default_table
    if column_table is None:
        return ()

    resolved_table = alias_map.get(column_table.lower(), column_table.lower())
    if resolved_table in cte_names:
        resolved = resolve_cte(resolved_table).get(column.name.lower())
        return resolved or ()

    return (ColumnReference(table=resolved_table, column=column.name),)


def _extract_cte_lineage(
    expression: SqlGlotExpression,
    *,
    cte_names: frozenset[str],
    resolve_cte: Callable[[str], Mapping[str, tuple[ColumnReference, ...]]],
    sql_dialect: str,
) -> dict[str, tuple[ColumnReference, ...]]:
    alias_map, default_table = _build_query_alias_map(expression, cte_names)
    lineage: dict[str, tuple[ColumnReference, ...]] = {}
    select_expressions = list(expression.expressions or [])
    if not select_expressions and isinstance(expression, exp.Query):
        select_node = expression.args.get("this")
        if isinstance(select_node, exp.Select):
            select_expressions = list(select_node.expressions or [])

    for select_expr in select_expressions:
        if select_expr is None:
            continue
        rendered = _render_sql(select_expr, sql_dialect)
        node = select_expr.this if isinstance(select_expr, exp.Alias) else select_expr
        column_refs: dict[tuple[str | None, str], ColumnReference] = {}
        for column in _iter_columns(node):
            if isinstance(column.this, exp.Star):
                continue
            resolved_refs = _resolve_column_references(
                column,
                alias_map=alias_map,
                default_table=default_table,
                cte_names=cte_names,
                resolve_cte=resolve_cte,
            )
            for ref in resolved_refs:
                key = (ref.table, ref.column)
                if key not in column_refs:
                    column_refs[key] = ref

        output_name = select_expr.alias_or_name or rendered
        lineage[output_name.lower()] = tuple(column_refs.values())
    return lineage


def _build_cte_lineage(
    expression: SqlGlotExpression,
) -> dict[str, dict[str, tuple[ColumnReference, ...]]]:
    cte_expressions: dict[str, SqlGlotExpression] = {}

    with_expr = expression.args.get("with")
    if isinstance(with_expr, exp.With):
        for cte in list(with_expr.expressions or []):
            if isinstance(cte, exp.CTE):
                alias = cte.alias_or_name
                if not alias:
                    continue
                cte_body = cte.this
                if isinstance(cte_body, exp.Subquery):
                    cte_body = cte_body.this
                if isinstance(cte_body, exp.Query):
                    cte_expressions[alias.lower()] = cte_body
                elif isinstance(cte_body, exp.Select):
                    cte_expressions[alias.lower()] = cte_body

    if not cte_expressions:
        for cte in expression.find_all(exp.CTE):
            alias = cte.alias_or_name
            if not alias:
                continue
            cte_body = cte.this
            if isinstance(cte_body, exp.Subquery):
                cte_body = cte_body.this
            if isinstance(cte_body, exp.Query):
                cte_expressions[alias.lower()] = cte_body
            elif isinstance(cte_body, exp.Select):
                cte_expressions[alias.lower()] = cte_body

    resolved: dict[str, dict[str, tuple[ColumnReference, ...]]] = {}
    resolving: set[str] = set()
    cte_names = frozenset(cte_expressions.keys())

    def resolve_cte(name: str) -> dict[str, tuple[ColumnReference, ...]]:
        if name in resolved:
            return resolved[name]
        if name in resolving:
            return {}
        resolving.add(name)
        cte_expr = cte_expressions.get(name)
        if cte_expr is None:
            resolving.remove(name)
            resolved[name] = {}
            return {}
        lineage = _extract_cte_lineage(
            cte_expr,
            sql_dialect="postgres",
            cte_names=cte_names,
            resolve_cte=resolve_cte,
        )
        resolved[name] = lineage
        resolving.remove(name)
        return lineage

    for name in cte_expressions:
        resolve_cte(name)

    if resolved:
        logger.info(
            "DQL CTE lineage resolved: %s",
            {
                cte: {
                    col: [(ref.table, ref.column) for ref in refs] for col, refs in mapping.items()
                }
                for cte, mapping in resolved.items()
            },
        )
    return resolved


def extract_selected_columns(
    expression: SqlGlotExpression,
    *,
    sql_dialect: str = "postgres",
) -> list[SelectedColumn]:
    """Materialize SELECT outputs and track their dependencies for downstream tooling."""

    if not isinstance(expression, exp.Query):
        raise DQLParseError("Expected a SELECT query expression.")

    cte_lineage = _build_cte_lineage(expression)
    cte_names = frozenset(cte_lineage.keys())
    alias_map, default_table = _build_query_alias_map(expression, cte_names)

    results: list[SelectedColumn] = []
    select_expressions_raw = list(expression.expressions or [])

    select_expressions: list[SqlGlotExpression] = []
    for raw in select_expressions_raw:
        if raw is None:
            continue
        assert isinstance(raw, exp.Expression)
        select_expressions.append(raw)

    for select_expr in select_expressions:
        rendered = _render_sql(select_expr, sql_dialect)
        node = select_expr.this if isinstance(select_expr, exp.Alias) else select_expr
        column_refs: dict[tuple[str | None, str], ColumnReference] = {}
        for column in _iter_columns(node):
            if isinstance(column.this, exp.Star):
                continue
            resolved_refs = _resolve_column_references(
                column,
                alias_map=alias_map,
                default_table=default_table,
                cte_names=cte_names,
                resolve_cte=lambda name: cte_lineage.get(name, {}),
            )
            for ref in resolved_refs:
                key = (ref.table, ref.column)
                if key not in column_refs:
                    column_refs[key] = ref

        output_name = select_expr.alias_or_name or rendered
        results.append(
            SelectedColumn(
                output_name=output_name,
                expression_sql=rendered,
                source_columns=tuple(column_refs.values()),
            )
        )

    logger.info(
        "DQL selected columns: %s",
        [
            {
                "output": column.output_name,
                "expression": column.expression_sql,
                "sources": [(ref.table, ref.column) for ref in column.source_columns],
            }
            for column in results
        ],
    )
    return results


def _ensure_select_only(expression: SqlGlotExpression) -> None:
    """Reject any query tree that attempts to mutate data or execute commands."""

    disallowed: tuple[type[exp.Expression], ...] = (
        exp.Delete,
        exp.Update,
        exp.Insert,
        exp.Command,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.Transaction,
        exp.Merge,
        exp.Set,
    )
    for node in expression.walk():
        if isinstance(node, disallowed):
            raise DQLValidationError("Only read-only SELECT queries are supported.")


def _ensure_allowed_expressions(expression: SqlGlotExpression) -> None:
    """Ensure every AST node uses a construct that DQL explicitly supports."""

    for node in expression.walk():
        if not isinstance(node, ALLOWED_EXPRESSION_TYPES):
            rendered = ""
            try:
                rendered = _render_sql(node, "postgres").strip()
            except Exception:
                rendered = str(node).strip()
            if rendered:
                if len(rendered) > 160:
                    rendered = rendered[:157] + "..."
                detail = f"\n\nOffending DQL fragment: {rendered}"
            else:
                detail = ""

            # Provide a helpful hint for COUNT(*) usage
            hint = ""
            if isinstance(node, exp.Star):
                hint = "\n\nHint: If using COUNT(*), try count() or count(1) instead."

            raise DQLValidationError(
                f"Expression type '{type(node).__name__}' is not allowed in Docent Query Language.{detail}{hint}"
            )

        # Additional validation for Anonymous functions - must be in whitelist
        if isinstance(node, exp.Anonymous):
            func_name = node.name.lower() if node.name else ""
            if func_name not in ALLOWED_ANONYMOUS_FUNCTIONS:
                raise DQLValidationError(
                    f"Function '{node.name}' is not allowed in Docent Query Language."
                )


def _validate_query_expression(
    expression: SqlGlotExpression,
    registry: DQLRegistry,
    collection_id: str,
) -> None:
    """Validate a parsed query and enforce collection scoping when an id is provided."""

    scope = cast(Scope, build_scope(expression))
    filter_applied = _validate_scope(scope, registry, collection_id, parent_alias_map=None)
    if not filter_applied:
        raise DQLValidationError(
            "DQL queries must reference collection-scoped tables when a collection id is supplied."
        )
    _ensure_non_negative_limits(expression)


def _validate_scope(
    scope: Scope,
    registry: DQLRegistry,
    collection_id: str,
    parent_alias_map: Mapping[str, AllowedTable] | None,
) -> bool:
    """Validate a scope and its descendants, returning whether a collection predicate was applied."""

    cached_scope = getattr(scope, "_collection_scoped", None)
    if isinstance(cached_scope, bool):
        return cached_scope

    base_alias_map: dict[str, AllowedTable] = {}
    derived_aliases: set[str] = set()
    derived_scopes: list[Scope] = []
    collection_filter_applied = False

    sources = cast(Mapping[str, object], getattr(scope, "sources", {}))

    for alias, source in sources.items():
        alias_key = alias.lower()
        if isinstance(source, exp.Table):
            table_name: str = source.name
            allowed_table = registry.get_table(table_name)
            base_alias_map[alias_key] = allowed_table
            base_alias_map.setdefault(table_name.lower(), allowed_table)

            if allowed_table.collection_predicate_factory:
                table_alias: str = source.alias_or_name or alias
                _apply_collection_filter(
                    scope,
                    table_alias,
                    allowed_table.collection_predicate_factory,
                    collection_id,
                )
                collection_filter_applied = True
        elif isinstance(source, Scope):
            derived_aliases.add(alias_key)
            derived_scopes.append(source)
        else:
            raise DQLValidationError(f"Unsupported FROM source type '{type(source).__name__}'.")

    # Merge parent aliases to allow correlated subqueries to reference outer tables
    merged_alias_map: dict[str, AllowedTable] = {}
    if parent_alias_map:
        merged_alias_map.update({k.lower(): v for k, v in parent_alias_map.items()})
    merged_alias_map.update(base_alias_map)

    columns = cast(Sequence[SqlGlotColumn], getattr(scope, "columns", []) or [])
    _validate_columns(columns, merged_alias_map, derived_aliases)
    _reject_stars(cast(SqlGlotExpression, scope.expression))

    child_scopes = list(_iter_scope_children(scope))
    if derived_scopes:
        child_scope_ids = {id(child) for child in child_scopes}
        for derived in derived_scopes:
            if id(derived) not in child_scope_ids:
                child_scopes.append(derived)
                child_scope_ids.add(id(derived))

    for child in child_scopes:
        if _validate_scope(child, registry, collection_id, parent_alias_map=merged_alias_map):
            collection_filter_applied = True

    # We must have at least one collection-scoped table
    if not collection_filter_applied:
        raise DQLValidationError("Must reference at least one table.")

    setattr(scope, "_collection_scoped", collection_filter_applied)
    return collection_filter_applied


def _validate_columns(
    columns: Sequence[SqlGlotColumn],
    base_alias_map: dict[str, AllowedTable],
    derived_aliases: set[str],
) -> None:
    """Ensure column references are qualified and map to whitelisted table columns."""

    if not columns:
        return

    unique_tables: tuple[AllowedTable, ...] = tuple(
        {id(table): table for table in base_alias_map.values()}.values()
    )

    for column in columns:
        if isinstance(column.this, exp.Star):
            continue

        column_name = column.name.lower()
        qualifier = column.table.lower() if column.table else None

        if qualifier is None:
            if not base_alias_map:
                continue
            if len(unique_tables) != 1:
                raise DQLValidationError(
                    f"Column '{column.sql()}' must be qualified when multiple tables are present."  # type: ignore[reportUnknownMemberType]
                )
            allowed_table = unique_tables[0]
            _resolve_column_name(allowed_table, column_name, column.sql())  # type: ignore[reportUnknownMemberType]
            continue

        if qualifier in derived_aliases:
            continue

        allowed_table = base_alias_map.get(qualifier)
        if not allowed_table:
            column_ref = column.sql()  # type: ignore[reportUnknownMemberType]
            raise DQLValidationError(
                f"Unknown table or alias '{column.table}' in column reference '{column_ref}'."
            )

        _resolve_column_name(allowed_table, column_name, column.sql())  # type: ignore[reportUnknownMemberType]


def _reject_stars(expression: SqlGlotExpression) -> None:
    """Fail fast when a query attempts to use '*' instead of explicit columns."""

    for _ in find_all_in_scope(expression, exp.Star):  # type: ignore[reportUnknownVariableType]
        raise DQLValidationError(
            "Wildcard selection is not allowed; explicitly list the permitted columns."
        )


def _ensure_non_negative_limits(expression: SqlGlotExpression) -> None:
    """Guard against LIMIT/OFFSET values that would cause unexpected pagination behavior."""

    for node in expression.walk():
        if isinstance(node, exp.Limit):
            value = _literal_to_int(node.expression)
            if value is not None and value < 0:
                raise DQLValidationError("LIMIT must be non-negative.")
        elif isinstance(node, exp.Offset):
            value = _literal_to_int(node.expression)
            if value is not None and value < 0:
                raise DQLValidationError("OFFSET must be non-negative.")


def _literal_to_int(expression: SqlGlotExpression | None) -> int | None:
    """Convert a sqlglot literal into an int so limit validation can compare values."""

    if expression is None:
        return None
    if isinstance(expression, exp.Literal) and not expression.is_string:
        try:
            return int(expression.this)
        except (TypeError, ValueError):
            return None
    if isinstance(expression, exp.Neg):
        inner = _literal_to_int(expression.this)
        if inner is not None:
            return -inner
    return None


def get_query_limit_value(expression: QueryExpression) -> int | None:
    """Expose the LIMIT value so callers can apply overrides or defaults before execution."""

    limit_expr = cast(exp.Limit | None, expression.args.get("limit"))
    if limit_expr is None:
        return None
    return _literal_to_int(limit_expr.expression)


def apply_limit_cap(expression: QueryExpression, limit_value: int) -> None:
    """Override the LIMIT clause with a cap so callers can enforce result bounds."""

    if limit_value <= 0:
        raise ValueError("limit_value must be positive.")

    literal = exp.Literal.number(limit_value)  # type: ignore[reportUnknownMemberType]
    existing = cast(exp.Limit | None, expression.args.get("limit"))
    if existing is None:
        expression.set("limit", exp.Limit(expression=literal))
        return

    existing.set("expression", literal)
