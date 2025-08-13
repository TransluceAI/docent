from typing import TYPE_CHECKING, Type

from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_

from docent._log_util import get_logger
from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.auth_models import User

if TYPE_CHECKING:
    from docent_core.docent.db.schemas.tables import SQLAAgentRun

logger = get_logger(__name__)


class ViewContext(BaseModel):
    collection_id: str
    view_id: str
    user: User | None
    base_filter: ComplexFilter | None

    def get_base_where_clause(self, SQLAAgentRun: Type["SQLAAgentRun"]) -> ColumnElement[bool]:
        # Make sure we're filtering by the correct collection_id
        base_clause = SQLAAgentRun.collection_id == self.collection_id

        if self.base_filter is None:
            return base_clause

        base_filter_clause = self.base_filter.to_sqla_where_clause(SQLAAgentRun)
        if base_filter_clause is None:
            return base_clause

        return and_(base_clause, base_filter_clause)
