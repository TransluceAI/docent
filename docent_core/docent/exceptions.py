"""
Custom exception classes for the Docent application.
"""


class UserFacingError(Exception):
    """Base exception for errors safe to show to users."""

    def __init__(self, user_message: str, internal_message: str | None = None):
        self.user_message = user_message
        self.internal_message = internal_message or user_message
        super().__init__(self.internal_message)


class DuplicateAgentRunError(UserFacingError):
    """Raised when ingesting a duplicate agent run ID."""

    def __init__(self, agent_run_id: str):
        super().__init__(
            user_message=f"An agent run with ID '{agent_run_id}' already exists.",
            internal_message=f"Duplicate agent run ID: {agent_run_id}",
        )
