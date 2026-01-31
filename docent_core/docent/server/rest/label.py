from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from jsonschema import SchemaError, ValidationError
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util.logger import get_logger
from docent.data_models import InlineCitation
from docent.data_models.judge import Label
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.label import Comment, LabelSet
from docent_core.docent.server.dependencies.database import get_session
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_agent_run_in_collection,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import get_label_service
from docent_core.docent.server.dependencies.user import get_user_anonymous_ok
from docent_core.docent.services.label import BulkValidationError, LabelService, LabelSetWithCount

logger = get_logger(__name__)

label_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


################
# Dependencies #
################


async def require_label_set_in_collection(
    collection_id: str,
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
) -> None:
    """Validate that label_set belongs to collection. Raises 404 if not."""
    label_set = await label_svc.get_label_set(label_set_id)
    if label_set is None or label_set.collection_id != collection_id:
        raise HTTPException(
            status_code=404,
            detail=f"Label set {label_set_id} not found in collection {collection_id}",
        )


async def get_label_in_collection(
    collection_id: str,
    label_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Validate that label belongs to collection via its label_set and return it."""
    from sqlalchemy import select

    from docent_core.docent.db.schemas.label import SQLALabel, SQLALabelSet

    result = await session.execute(
        select(SQLALabel)
        .join(SQLALabelSet, SQLALabelSet.id == SQLALabel.label_set_id)
        .where(SQLALabel.id == label_id)
        .where(SQLALabelSet.collection_id == collection_id)
    )
    sqla_label = result.scalar_one_or_none()
    if sqla_label is None:
        raise HTTPException(
            status_code=404, detail=f"Label {label_id} not found in collection {collection_id}"
        )
    return sqla_label.to_pydantic()


async def require_tag_in_collection(
    collection_id: str,
    tag_id: str,
    label_svc: LabelService = Depends(get_label_service),
) -> None:
    """Validate that tag belongs to collection. Raises 404 if not."""
    from sqlalchemy import select

    from docent_core.docent.db.schemas.label import SQLATag

    result = await label_svc.session.execute(select(SQLATag).where(SQLATag.id == tag_id))
    tag = result.scalar_one_or_none()
    if tag is None or tag.collection_id != collection_id:
        raise HTTPException(
            status_code=404, detail=f"Tag {tag_id} not found in collection {collection_id}"
        )


async def require_comment_in_collection(
    collection_id: str,
    comment_id: str,
    label_svc: LabelService = Depends(get_label_service),
) -> None:
    """Validate that comment belongs to collection. Raises 404 if not."""
    comment = await label_svc.get_comment(comment_id)
    if comment is None or comment.collection_id != collection_id:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found in collection {collection_id}",
        )


################
# Request Models
################


class CreateLabelRequest(BaseModel):
    label: Label


class CreateLabelsRequest(BaseModel):
    labels: list[Label]


class UpdateLabelRequest(BaseModel):
    label_value: dict[str, Any]


class CreateLabelSetRequest(BaseModel):
    name: str
    description: str | None = None
    label_schema: dict[str, Any]


class UpdateLabelSetRequest(BaseModel):
    name: str
    description: str | None = None
    label_schema: dict[str, Any]


class CreateCommentRequest(BaseModel):
    citations: list[InlineCitation]
    content: str


class UpdateCommentRequest(BaseModel):
    content: str


class CreateTagRequest(BaseModel):
    agent_run_id: str
    value: str


class CategorizedLabelSetsResponse(BaseModel):
    available: list[LabelSet]
    filled: list[LabelSet]


################
# Label CRUD
################


@label_router.post("/{collection_id}/label")
async def create_label(
    collection_id: str,
    request: CreateLabelRequest,
    label_svc: LabelService = Depends(get_label_service),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Create a label."""

    try:
        await label_svc.create_label(request.label)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.message)

    # Flush to surface constraint violations as proper HTTP errors
    try:
        await session.flush()
    except IntegrityError as e:
        # Unique constraint violation (Postgres SQLSTATE 23505)
        if getattr(e.orig, "pgcode", None) == "23505":
            raise HTTPException(
                status_code=409,
                detail=f"A label already exists for agent_run_id={request.label.agent_run_id} and label_set_id={request.label.label_set_id}",
            )
        raise

    return {"message": "Label created successfully"}


@label_router.post("/{collection_id}/labels")
async def create_labels(
    collection_id: str,
    request: CreateLabelsRequest,
    label_svc: LabelService = Depends(get_label_service),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Create multiple labels."""
    try:
        await label_svc.create_labels(request.labels)
    except BulkValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Flush to surface constraint violations as proper HTTP errors
    try:
        await session.flush()
    except IntegrityError as e:
        # Unique constraint violation (Postgres SQLSTATE 23505)
        if getattr(e.orig, "pgcode", None) == "23505":
            raise HTTPException(
                status_code=409,
                detail="One or more labels already exist for the given agent_run_id and label_set_id combinations",
            )
        raise

    return {"message": "Labels created successfully"}


@label_router.get("/{collection_id}/label/{label_id}")
async def get_label(
    collection_id: str,
    label_id: str,
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    label: Label = Depends(get_label_in_collection),
) -> Label:
    """Get a label by ID."""
    return label


@label_router.put("/{collection_id}/label/{label_id}")
async def update_label(
    collection_id: str,
    label_id: str,
    request: UpdateLabelRequest,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _label: Label = Depends(get_label_in_collection),
) -> dict[str, str]:
    """Update a label."""
    await label_svc.update_label(label_id, request.label_value)
    return {"message": "Label updated successfully"}


@label_router.delete("/{collection_id}/label/{label_id}")
async def delete_label(
    collection_id: str,
    label_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _label: Label = Depends(get_label_in_collection),
) -> dict[str, str]:
    """Delete a label."""
    await label_svc.delete_label(label_id)
    return {"message": "Label deleted successfully"}


@label_router.delete("/{collection_id}/label_set/{label_set_id}/labels")
async def delete_labels_by_label_set(
    collection_id: str,
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _label_set: None = Depends(require_label_set_in_collection),
) -> dict[str, str]:
    """Delete all labels in a label set."""
    await label_svc.delete_labels_by_label_set(label_set_id)
    return {"message": "Labels deleted successfully"}


############
# Tag CRUD #
############


@label_router.post("/{collection_id}/tag")
async def create_tag(
    collection_id: str,
    request: CreateTagRequest,
    label_svc: LabelService = Depends(get_label_service),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
):
    """Create a tag for an agent run."""
    try:
        await label_svc.create_tag(
            collection_id=collection_id,
            agent_run_id=request.agent_run_id,
            value=request.value,
            created_by=user.id,
        )
    except LabelService.AgentRunCollectionMismatchError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IntegrityError as e:
        if getattr(e.orig, "pgcode", None) == "23505":  # Unique constraint violation
            raise HTTPException(
                status_code=409,
                detail=f"Tag values must be unique per agent run; value {request.value} already exists for agent run {request.agent_run_id}",
            )
        raise


@label_router.delete("/{collection_id}/tag/{tag_id}")
async def delete_tag(
    tag_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _tag: None = Depends(require_tag_in_collection),
):
    """Delete a tag by ID."""
    if not await label_svc.delete_tag(tag_id):
        raise HTTPException(status_code=404, detail=f"Tag {tag_id} not found")


@label_router.get("/{collection_id}/tags")
async def get_tags_by_value(
    collection_id: str,
    value: str | None = Query(default=None, max_length=255),
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get all tags in a collection, optionally filtered by value."""
    return [sqla_tag.dict() for sqla_tag in await label_svc.get_tags_by_value(collection_id, value)]


@label_router.get("/{collection_id}/agent_run/{agent_run_id}/tags")
async def get_tags_for_agent_run(
    collection_id: str,
    agent_run_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
):
    """Get all tags for a specific agent run in a collection."""
    return [
        sqla_tag.dict()
        for sqla_tag in await label_svc.get_tags_for_agent_run(collection_id, agent_run_id)
    ]


##################
# Label Set CRUD #
##################


@label_router.post("/{collection_id}/label_set")
async def create_label_set(
    collection_id: str,
    request: CreateLabelSetRequest,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Create a label set."""
    try:
        label_set_id = await label_svc.create_label_set(
            collection_id, request.name, request.label_schema, description=request.description
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid label schema: {e.message}")
    except SchemaError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON Schema: {e.message}")
    return {"label_set_id": label_set_id}


@label_router.get("/{collection_id}/label_set/{label_set_id}")
async def get_label_set(
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    _label_set: None = Depends(require_label_set_in_collection),
) -> LabelSet:
    """Get a label set by ID."""
    label_set = await label_svc.get_label_set(label_set_id)
    if label_set is None:
        raise HTTPException(status_code=404, detail=f"Label set {label_set_id} not found")
    return label_set.to_pydantic()


@label_router.get("/{collection_id}/label_sets")
async def get_all_label_sets(
    collection_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[LabelSet]:
    """Get all label sets."""
    label_sets = await label_svc.get_all_label_sets(collection_id)
    return [ls.to_pydantic() for ls in label_sets]


@label_router.get("/{collection_id}/label_sets_with_counts")
async def get_label_sets_with_counts(
    collection_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[LabelSetWithCount]:
    """Get all label sets with label counts."""
    return await label_svc.get_label_sets_with_counts(collection_id)


@label_router.put("/{collection_id}/label_set/{label_set_id}")
async def update_label_set(
    label_set_id: str,
    request: UpdateLabelSetRequest,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _label_set: None = Depends(require_label_set_in_collection),
) -> dict[str, str]:
    """Update a label set."""
    try:
        await label_svc.update_label_set(
            label_set_id, request.name, request.label_schema, request.description
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid label schema: {e.message}")
    except SchemaError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON Schema: {e.message}")
    return {"message": "Label set updated successfully"}


@label_router.get("/{collection_id}/label_set/{label_set_id}/labels")
async def get_labels_in_label_set(
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
    filter_valid_labels: bool = Query(default=False),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    _label_set: None = Depends(require_label_set_in_collection),
) -> list[Label]:
    """Get all labels in a label set."""
    return await label_svc.get_labels_by_label_set(label_set_id, filter_valid_labels)


@label_router.delete("/{collection_id}/label_set/{label_set_id}")
async def delete_label_set(
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _label_set: None = Depends(require_label_set_in_collection),
) -> dict[str, str]:
    """Delete a label set."""
    await label_svc.delete_label_set(label_set_id)
    return {"message": "Label set deleted successfully"}


@label_router.get("/{collection_id}/agent_run/{agent_run_id}/labels")
async def get_labels_for_agent_run(
    agent_run_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    _run: None = Depends(require_agent_run_in_collection),
) -> list[Label]:
    """Get all labels for a specific agent run."""
    return await label_svc.get_labels_by_agent_run(agent_run_id)


@label_router.get("/{collection_id}/agent_run/{agent_run_id}/label_sets_categorized")
async def get_label_sets_categorized(
    collection_id: str,
    agent_run_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    _run: None = Depends(require_agent_run_in_collection),
) -> CategorizedLabelSetsResponse:
    """Get label sets split by whether they have a label for this agent run."""
    available, filled = await label_svc.get_label_sets_categorized_for_agent_run(
        collection_id, agent_run_id
    )
    return CategorizedLabelSetsResponse(
        available=[ls.to_pydantic() for ls in available],
        filled=[ls.to_pydantic() for ls in filled],
    )


################
# Comment CRUD #
################


@label_router.post("/{collection_id}/agent_run/{agent_run_id}/comment")
async def create_comment(
    collection_id: str,
    agent_run_id: str,
    request: CreateCommentRequest,
    label_svc: LabelService = Depends(get_label_service),
    user: User = Depends(get_user_anonymous_ok),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _run: None = Depends(require_agent_run_in_collection),
) -> dict[str, str]:
    """Create a comment."""
    logger.info(f"Creating comment for user {user.email}")
    await label_svc.create_comment(
        user.id,
        collection_id=collection_id,
        agent_run_id=agent_run_id,
        citations=request.citations,
        content=request.content,
    )
    return {"message": "Comment created successfully"}


@label_router.put("/{collection_id}/comment/{comment_id}")
async def update_comment(
    collection_id: str,
    comment_id: str,
    request: UpdateCommentRequest,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _comment: None = Depends(require_comment_in_collection),
) -> dict[str, str]:
    """Update a comment."""
    await label_svc.update_comment(comment_id, request.content)
    return {"message": "Comment updated successfully"}


@label_router.delete("/{collection_id}/comment/{comment_id}")
async def delete_comment(
    comment_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.WRITE)),
    _comment: None = Depends(require_comment_in_collection),
) -> dict[str, str]:
    """Delete a comment."""
    await label_svc.delete_comment(comment_id)
    return {"message": "Comment deleted successfully"}


@label_router.get("/{collection_id}/agent_run/{agent_run_id}/comments")
async def get_comments_by_agent_run(
    agent_run_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
    _run: None = Depends(require_agent_run_in_collection),
) -> list[Comment]:
    """Get all comments for a specific agent run."""
    return await label_svc.get_comments_by_agent_run(agent_run_id)


@label_router.get("/{collection_id}/comments")
async def get_comments_by_collection(
    collection_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _perm: None = Depends(require_collection_permission(Permission.READ)),
) -> list[Comment]:
    """Get all comments in a collection."""
    return await label_svc.get_comments_by_collection(collection_id)
