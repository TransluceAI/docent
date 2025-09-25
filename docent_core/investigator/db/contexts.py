from pydantic import BaseModel

from docent._log_util import get_logger
from docent_core.docent.db.filters import ComplexFilter
from docent_core.docent.db.schemas.auth_models import User

logger = get_logger(__name__)


class WorkspaceContext(BaseModel):
    workspace_id: str
    user: User | None
    base_filter: ComplexFilter | None
