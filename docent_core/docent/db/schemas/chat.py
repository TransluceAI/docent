from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from docent._log_util import get_logger
from docent.data_models.chat.message import ChatMessage, parse_chat_message
from docent_core._db_service.schemas.base import SQLABase
from docent_core._llm_util.providers.preferences import ModelOption
from docent_core.docent.db.schemas.rubric import TABLE_JUDGE_RESULT
from docent_core.docent.db.schemas.tables import TABLE_AGENT_RUN, TABLE_USER

TABLE_CHAT_SESSION = "chat_sessions"

logger = get_logger(__name__)


class ChatSession(BaseModel):
    id: str
    agent_run_id: str | None = None
    judge_result_id: str | None
    messages: list[ChatMessage]
    chat_model: ModelOption | None = None
    estimated_input_tokens: int | None = None

    # Error messages are sent over SSE when they happen, but not stored in the db
    error_message: str | None = None


class SQLAChatSession(SQLABase):
    __tablename__ = TABLE_CHAT_SESSION

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True
    )

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id", ondelete="CASCADE"), nullable=True
    )
    judge_result_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_JUDGE_RESULT}.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    chat_model: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # JSON field to store all messages
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    # Token count from most recent API call (input + output tokens)
    estimated_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False, index=True
    )

    def to_pydantic(self) -> ChatSession:
        chat_model = None
        if self.chat_model:
            try:
                chat_model = ModelOption.model_validate(self.chat_model)
            except ValidationError as e:
                logger.error(f"Error validating chat model: {e}")
                chat_model = None
        return ChatSession(
            id=self.id,
            agent_run_id=self.agent_run_id,
            judge_result_id=self.judge_result_id,
            messages=[parse_chat_message(m) for m in self.messages],
            chat_model=chat_model,
            estimated_input_tokens=self.estimated_input_tokens,
        )

    @classmethod
    def from_pydantic(cls, session: ChatSession) -> "SQLAChatSession":
        chat_model = None
        if session.chat_model:
            try:
                chat_model = session.chat_model.model_dump()
            except ValidationError as e:
                logger.error(f"Error validating chat model: {e}")
                chat_model = None

        return cls(
            id=session.id,
            agent_run_id=session.agent_run_id,
            judge_result_id=session.judge_result_id,
            messages=[m.model_dump() for m in session.messages],
            chat_model=chat_model,
        )
