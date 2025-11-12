from datetime import datetime

from pydantic import BaseModel


class Collection(BaseModel):
    """Represents a collection of agent runs.

    A Collection is a container for organizing and managing related agent runs.

    Attributes:
        id: Unique identifier for the collection.
        name: Human-readable name for the collection.
        description: Optional description of the collection's purpose.
        created_by: User ID of the collection creator (if available).
        created_at: Timestamp when the collection was created.
    """

    id: str
    name: str | None = None
    description: str | None = None
    created_by: str | None = None
    created_at: datetime
