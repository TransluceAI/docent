from uuid import uuid4

from pydantic import Field, model_validator

from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import Transcript


class FormattedTranscript(Transcript):
    """A Transcript that preserves original message indices during edits.

    This class extends Transcript to support customization while maintaining accurate
    citations. Each message retains its original index from the source transcript,
    even if messages are added, removed, or reordered.

    Use this class when you need to customize which parts of a transcript are visible
    to an LLM while ensuring citations remain valid.
    """

    id_to_original_index: dict[str, int]

    @classmethod
    def from_transcript(cls, transcript: Transcript) -> "FormattedTranscript":
        """Create a FormattedTranscript from a regular Transcript."""
        # Ensure all messages have IDs and build id_to_original_index
        id_to_original_index: dict[str, int] = {}
        for idx, msg in enumerate(transcript.messages):
            if msg.id is None:
                msg.id = str(uuid4())
            id_to_original_index[msg.id] = idx

        return cls(
            id=transcript.id,
            name=transcript.name,
            description=transcript.description,
            transcript_group_id=transcript.transcript_group_id,
            created_at=transcript.created_at,
            messages=transcript.messages,
            metadata=transcript.metadata,
            id_to_original_index=id_to_original_index,
        )

    @model_validator(mode="after")
    def _validate_id_to_original_index(self) -> "FormattedTranscript":
        """Ensure id_to_original_index covers all messages."""
        for msg in self.messages:
            if msg.id not in self.id_to_original_index:
                raise ValueError(
                    f"Message {msg.id} missing from id_to_original_index. "
                    "Use FormattedTranscript.from_transcript() to create a new instance."
                )
        return self

    def _enumerate_messages(self):
        """Yield (original index, message) for each message."""
        for message in self.messages:
            assert message.id is not None
            original_idx = self.id_to_original_index[message.id]
            yield (original_idx, message)


class FormattedAgentRun(AgentRun):
    """An AgentRun that allows customization while tracking original identifiers.

    This class extends AgentRun to support modifications to what an LLM sees
    while maintaining accurate citations back to the original agent run.

    Use this class when you need to customize which parts of an agent run are visible
    to an LLM (e.g., hiding metadata, truncating long outputs).
    """

    transcripts: list[FormattedTranscript] = Field(default_factory=list)  # type: ignore[assignment]

    @classmethod
    def from_agent_run(cls, agent_run: AgentRun) -> "FormattedAgentRun":
        """Create a FormattedAgentRun from a regular AgentRun."""
        return cls(
            id=agent_run.id,
            name=agent_run.name,
            description=agent_run.description,
            transcripts=[FormattedTranscript.from_transcript(t) for t in agent_run.transcripts],
            transcript_groups=agent_run.transcript_groups,
            metadata=agent_run.metadata,
        )
