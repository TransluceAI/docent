"""
Steps of refinement:
- Search for possible matches
- Generate a list of ambiguities
- Generate a v1 rubric proposal
"""

from copy import deepcopy
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent.data_models.chat.message import ChatMessage, UserMessage, parse_chat_message
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.rubric import TABLE_RUBRIC

if TYPE_CHECKING:
    from docent_core.docent.db.schemas.rubric import SQLARubric

TABLE_REFINEMENT_AGENT_SESSION = "refinement_agent_sessions"


class RefinementStatus(str, Enum):
    READING_DATA = "reading_data"
    INITIAL_FEEDBACK = "initial_feedback"
    ASKING_QUESTIONS = "asking_questions"
    DONE = "done"

    # Default
    DEFAULT_STATUS = "reading_data"


class RefinementAgentSession(BaseModel):
    id: str
    rubric_id: str
    rubric_version: int
    messages: list[ChatMessage]
    n_summaries: Optional[int] = Field(
        default=None, description="Number of summaries generated at the start of the conversation."
    )
    # Deprecated
    status: Optional[RefinementStatus] = Field(default=None, description="Deprecated")
    error_message: Optional[str] = Field(
        default=None, description="Error message from the refinement agent"
    )

    def prepare_for_client(self, error: str | None = None) -> "RefinementAgentSession":
        """This function trims the session for the SSE callback.
        the FE doesn't need all session state

        Trim the system message at position 0 and initial rubric at position 2
        Furthermore, trim all tool messages in response to rewrite_rubric tool calls
        """

        messages = self.model_copy().messages
        cleaned_messages = [
            # Replace messages triggered when the user manually updates the rubric
            (
                UserMessage(content="The user has updated the rubric.")
                if (
                    message.role == "user"
                    and message.text.startswith("The user updated the rubric from v")
                )
                else message
            )
            for message in messages[1:2] + messages[3:]
        ]

        return self.model_copy(
            update={
                "messages": cleaned_messages,
                "error_message": error,
            }
        )


class SQLARefinementAgentSession(SQLABase):
    __tablename__ = TABLE_REFINEMENT_AGENT_SESSION

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    rubric_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Composite foreign key constraint
    __table_args__ = (
        ForeignKeyConstraint(
            ["rubric_id", "rubric_version"],
            [f"{TABLE_RUBRIC}.id", f"{TABLE_RUBRIC}.version"],
        ),
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False, index=True
    )

    # Relationship back to rubric for ORM-level cascading
    rubric: Mapped["SQLARubric"] = relationship(
        "SQLARubric",
        back_populates="refinement_sessions",
    )

    def to_pydantic(self) -> RefinementAgentSession:
        content = deepcopy(self.content)
        content["messages"] = [parse_chat_message(m) for m in content["messages"]]
        return RefinementAgentSession.model_validate(content)

    @classmethod
    def from_pydantic(cls, session: RefinementAgentSession) -> "SQLARefinementAgentSession":
        return cls(
            id=session.id,
            rubric_id=session.rubric_id,
            rubric_version=session.rubric_version,
            content=session.model_dump(),
        )
