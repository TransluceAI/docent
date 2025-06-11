from enum import Enum

from pydantic import BaseModel

PERMISSION_LEVELS = {
    "read": 1,
    "write": 2,
    "admin": 3,
}


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"

    def includes(self, other: "Permission") -> bool:
        return PERMISSION_LEVELS[self.value] >= PERMISSION_LEVELS[other.value]


class SubjectType(str, Enum):
    USER = "user"
    ORGANIZATION = "organization"
    PUBLIC = "public"


class ResourceType(str, Enum):
    FRAME_GRID = "frame_grid"
    VIEW = "view"


class User(BaseModel):
    id: str
    email: str
    organization_ids: list[str]
    is_anonymous: bool = False
