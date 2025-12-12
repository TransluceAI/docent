from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent.data_models.chat.message import DocentChatMessage, parse_docent_chat_message
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.rubric import TABLE_JUDGE_RESULT
from docent_core.docent.db.schemas.tables import (
    TABLE_AGENT_RUN,
    TABLE_COLLECTION,
    TABLE_USER,
)

TABLE_CHAT_SESSION = "chat_sessions"

logger = get_logger(__name__)


class ChatSession(BaseModel):
    id: str
    collection_id: str | None = None
    agent_run_id: str | None = None
    judge_result_id: str | None
    messages: list[DocentChatMessage]
    chat_model: ModelOption | None = None
    estimated_input_tokens: int | None = None
    estimated_messages_tokens: int | None = None
    context_serialized: dict[str, Any] | None = None

    # Per-item token estimates for multi-run sessions (computed on read, not stored).
    # Maps alias (e.g., "R0", "R1") to token count.
    item_token_estimates: dict[str, int] | None = None

    # Errors are sent over SSE when they happen, but not stored in the db
    error_id: str | None = None
    error_message: str | None = None


class ChatSessionSummary(BaseModel):
    id: str
    collection_id: str | None = None
    message_count: int
    context_item_count: int
    updated_at: datetime
    first_message_preview: str | None = None


class SQLAChatSession(SQLABase):
    __tablename__ = TABLE_CHAT_SESSION

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True
    )
    collection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=True, index=True
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

    # Ground truth tokens minus context estimate at time of last API call.
    # Used to anchor token estimates when visibility changes.
    estimated_messages_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Serialized LLMContext for multi-object chat sessions
    context_serialized: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

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
            collection_id=self.collection_id,
            agent_run_id=self.agent_run_id,
            judge_result_id=self.judge_result_id,
            messages=[parse_docent_chat_message(m) for m in self.messages],
            chat_model=chat_model,
            estimated_input_tokens=self.estimated_input_tokens,
            estimated_messages_tokens=self.estimated_messages_tokens,
            context_serialized=self.context_serialized,
        )

    def to_summary(self) -> ChatSessionSummary:
        message_count = len(self.messages) if self.messages else 0
        context_item_count = 0
        if self.context_serialized:
            root_items = self.context_serialized.get("root_items")
            if isinstance(root_items, list):
                context_item_count = len(cast(list[Any], root_items))

        first_message_preview = None
        if self.messages:
            for msg_dict in self.messages:
                if msg_dict.get("role") == "user":
                    content = msg_dict.get("content", "")
                    if isinstance(content, str):
                        first_message_preview = content[:100]
                    elif isinstance(content, list):
                        text_parts: list[str] = []
                        content_list = cast(list[Any], content)
                        for item in content_list:
                            if isinstance(item, dict):
                                item_dict = cast(dict[str, Any], item)
                                text = item_dict.get("text")
                                item_type = item_dict.get("type")
                                if item_type == "text" and isinstance(text, str):
                                    text_parts.append(text)
                        if text_parts:
                            first_message_preview = " ".join(text_parts)[:100]
                    break

        return ChatSessionSummary(
            id=self.id,
            collection_id=self.collection_id,
            message_count=message_count,
            context_item_count=context_item_count,
            updated_at=self.updated_at,
            first_message_preview=first_message_preview,
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
            collection_id=session.collection_id,
            agent_run_id=session.agent_run_id,
            judge_result_id=session.judge_result_id,
            messages=[m.model_dump() for m in session.messages],
            chat_model=chat_model,
            estimated_messages_tokens=session.estimated_messages_tokens,
            context_serialized=session.context_serialized,
        )
