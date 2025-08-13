from typing import Literal

from pydantic import BaseModel

from docent_core.docent.db.schemas.auth_models import Organization, Permission, SubjectType, User
from docent_core.docent.db.schemas.tables import (
    SQLAAccessControlEntry,
    SQLAOrganization,
    SQLAUser,
)


class CollectionCollaborator(BaseModel):
    collection_id: str
    subject_type: SubjectType
    subject_id: str
    subject: User | Organization | Literal["public"]
    permission_level: Permission

    @classmethod
    def from_sqla_acl(cls, sqla_acl: SQLAAccessControlEntry) -> "CollectionCollaborator":
        assert sqla_acl.collection_id is not None
        subject_type = (
            SubjectType.USER
            if sqla_acl.user_id
            else SubjectType.ORGANIZATION if sqla_acl.organization_id else SubjectType.PUBLIC
        )
        subject = sqla_acl.subject()
        if isinstance(subject, SQLAUser):
            subject = subject.to_user()
        elif isinstance(subject, SQLAOrganization):
            subject = subject.to_organization()

        return cls(
            collection_id=sqla_acl.collection_id,
            subject_type=subject_type,
            subject_id=(
                sqla_acl.user_id
                if subject_type == SubjectType.USER
                else (
                    sqla_acl.organization_id
                    if subject_type == SubjectType.ORGANIZATION
                    else "public"
                )
            ),
            subject=subject,
            permission_level=sqla_acl.permission,
        )


class ViewCollaborator(BaseModel):
    view_id: str
    subject_type: SubjectType
    subject_id: str
    subject: User | Organization | Literal["public"]
    permission_level: Permission

    @classmethod
    def from_sqla_acl(cls, sqla_acl: SQLAAccessControlEntry) -> "ViewCollaborator":
        assert sqla_acl.view_id is not None
        subject_type = (
            SubjectType.USER
            if sqla_acl.user_id
            else SubjectType.ORGANIZATION if sqla_acl.organization_id else SubjectType.PUBLIC
        )
        subject = sqla_acl.subject()
        if isinstance(subject, SQLAUser):
            subject = subject.to_user()
        elif isinstance(subject, SQLAOrganization):
            subject = subject.to_organization()

        return cls(
            view_id=sqla_acl.view_id,
            subject_type=subject_type,
            subject_id=(
                sqla_acl.user_id
                if subject_type == SubjectType.USER
                else (
                    sqla_acl.organization_id
                    if subject_type == SubjectType.ORGANIZATION
                    else "public"
                )
            ),
            subject=subject,
            permission_level=sqla_acl.permission,
        )
