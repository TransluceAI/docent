from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from docent.data_models.chat.message import ChatMessage, parse_chat_message
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.rubric import TABLE_JUDGE_RESULT
from docent_core.docent.db.schemas.tables import TABLE_AGENT_RUN, TABLE_USER

TABLE_CHAT_SESSION = "chat_sessions"


class ChatSession(BaseModel):
    id: str
    agent_run_id: str | None = None
    judge_result_id: str | None
    messages: list[ChatMessage]


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

    # JSON field to store all messages
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False, index=True
    )

    def to_pydantic(self) -> ChatSession:
        return ChatSession(
            id=self.id,
            agent_run_id=self.agent_run_id,
            judge_result_id=self.judge_result_id,
            messages=[parse_chat_message(m) for m in self.messages],
        )

    @classmethod
    def from_pydantic(cls, session: ChatSession) -> "SQLAChatSession":
        return cls(
            id=session.id,
            agent_run_id=session.agent_run_id,
            judge_result_id=session.judge_result_id,
            messages=[m.model_dump() for m in session.messages],
        )
