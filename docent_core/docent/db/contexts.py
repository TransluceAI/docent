from typing import Any, Type

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, and_

from docent._log_util import get_logger
from docent_core.docent.db.filters import CollectionFilter, FilterSQLContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import SQLAAgentRun

logger = get_logger(__name__)


class ViewContext(BaseModel):
    collection_id: str
    view_id: str
    user: User | None
    base_filter: CollectionFilter | None

    def apply_base_filter(self, query: Select[Any]) -> Select[Any]:
        """Applies the base filter to the query.
        First runs `to_sqla_where_clause` on the base filter to get the WHERE clause and JOINs.
        Then applies the JOINs, then the WHERE clause.

        This replaces the old pattern of the caller manually managing this flow.
        """
        if self.base_filter is None:
            return query

        # Process the base filter to get the WHERE clause _and_ necessary JOINs
        # Note: `to_sqla_where_clause` mutates the filter context to track this information.
        filter_ctx = FilterSQLContext(SQLAAgentRun)
        base_filter_clause = self._get_base_where_clause(SQLAAgentRun, context=filter_ctx)

        # Apply joins if necessary
        for join_spec in filter_ctx.required_joins():
            query = query.join(join_spec.alias, join_spec.onclause)

        # Apply the where clause, after JOINs
        query = query.where(base_filter_clause)

        return query

    def _get_base_where_clause(
        self,
        SQLAAgentRun: Type["SQLAAgentRun"],
        *,
        context: FilterSQLContext | None = None,
    ) -> ColumnElement[bool]:
        # Make sure we're filtering by the correct collection_id
        base_clause = SQLAAgentRun.collection_id == self.collection_id

        if self.base_filter is None:
            return base_clause

        base_filter_clause = self.base_filter.to_sqla_where_clause(
            SQLAAgentRun,
            context=context,
        )
        if base_filter_clause is None:
            return base_clause

        return and_(base_clause, base_filter_clause)


class TelemetryContext(BaseModel):
    """
    Minimal context for telemetry ingest jobs that are not tied to a specific collection/view.
    """

    user: User | None
