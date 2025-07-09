from typing import AsyncContextManager, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core._ai_tools.rubric.rubric import Rubric
from docent_core._db_service.service import MonoService

logger = get_logger(__name__)


class RubricService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        service: MonoService,
    ):
        """The `session_cm_factory` creates new sessions that commit writes immediately.
        This is helpful if you don't want to wait for results to be written."""

        self.session = session
        self.session_cm_factory = session_cm_factory
        self.service = service

    def evaluate_rubric(self, rubric: Rubric, text: str):
        pass
