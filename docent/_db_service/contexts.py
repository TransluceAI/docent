from typing import TYPE_CHECKING, Type

from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_

from docent.data_models.filters import ComplexFilter

if TYPE_CHECKING:
    from docent._db_service.schemas.tables import SQLAAgentRun

from docent._db_service.schemas.auth_models import User

class ViewContext(BaseModel):
    fg_id: str
    view_id: str
    user: User | None
    base_filter: ComplexFilter | None

    def get_base_where_clause(self, SQLAAgentRun: Type["SQLAAgentRun"]) -> ColumnElement[bool]:
        # Make sure the fg_id matches
        clause = SQLAAgentRun.fg_id == self.fg_id

        # If there is a base filter, add it to the clause
        base_filter_clause = (
            self.base_filter.to_sqla_where_clause(SQLAAgentRun) if self.base_filter else None
        )
        if base_filter_clause is not None:
            clause = and_(clause, base_filter_clause)

        return clause
