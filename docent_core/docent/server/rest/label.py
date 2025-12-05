from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from jsonschema import ValidationError
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util.logger import get_logger
from docent.data_models import InlineCitation
from docent.data_models.judge import Label
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.label import Annotation, LabelSet
from docent_core.docent.server.dependencies.database import get_session
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import get_label_service, get_mono_svc
from docent_core.docent.server.dependencies.user import get_user_anonymous_ok
from docent_core.docent.services.label import BulkValidationError, LabelService, LabelSetWithCount
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)

label_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


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


class CreateAnnotationRequest(BaseModel):
    agent_run_id: str
    citations: list[InlineCitation]
    content: str


class UpdateAnnotationRequest(BaseModel):
    content: str


class CreateTagRequest(BaseModel):
    agent_run_id: str
    value: str


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
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> Label:
    """Get a label by ID."""
    label = await label_svc.get_label(label_id)
    if label is None:
        raise HTTPException(status_code=404, detail=f"Label {label_id} not found")
    return label


@label_router.put("/{collection_id}/label/{label_id}")
async def update_label(
    collection_id: str,
    label_id: str,
    request: UpdateLabelRequest,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Update a label."""
    await label_svc.update_label(label_id, request.label_value)
    return {"message": "Label updated successfully"}


@label_router.delete("/{collection_id}/label/{label_id}")
async def delete_label(
    collection_id: str,
    label_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Delete a label."""
    await label_svc.delete_label(label_id)
    return {"message": "Label deleted successfully"}


@label_router.delete("/{collection_id}/label_set/{label_set_id}/labels")
async def delete_labels_by_label_set(
    collection_id: str,
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Delete all labels in a label set."""
    # Verify the label set belongs to this collection
    label_set = await label_svc.get_label_set(label_set_id)
    if label_set is None:
        raise HTTPException(status_code=404, detail=f"Label set {label_set_id} not found")
    if label_set.collection_id != collection_id:
        raise HTTPException(
            status_code=404,
            detail=f"Label set {label_set_id} not found in collection {collection_id}",
        )

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
    _: None = Depends(require_collection_permission(Permission.WRITE)),
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
    _: None = Depends(require_collection_permission(Permission.READ)),
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
    label_set_id = await label_svc.create_label_set(
        collection_id, request.name, request.label_schema, description=request.description
    )
    return {"label_set_id": label_set_id}


@label_router.get("/{collection_id}/label_set/{label_set_id}")
async def get_label_set(
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
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
    collection_id: str,
    label_set_id: str,
    request: UpdateLabelSetRequest,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Update a label set."""
    await label_svc.update_label_set(
        label_set_id, request.name, request.label_schema, request.description
    )
    return {"message": "Label set updated successfully"}


@label_router.get("/{collection_id}/label_set/{label_set_id}/labels")
async def get_labels_in_label_set(
    collection_id: str,
    label_set_id: str,
    label_svc: LabelService = Depends(get_label_service),
    filter_valid_labels: bool = Query(default=False),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[Label]:
    """Get all labels in a label set."""
    return await label_svc.get_labels_by_label_set(label_set_id, filter_valid_labels)


@label_router.delete("/{collection_id}/label_set/{label_set_id}")
async def delete_label_set(
    collection_id: str,
    label_set_id: str,
    session: AsyncSession = Depends(get_session),
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Delete a label set."""
    await label_svc.delete_label_set(label_set_id)
    return {"message": "Label set deleted successfully"}


@label_router.get("/{collection_id}/agent_run/{agent_run_id}/labels")
async def get_labels_for_agent_run(
    collection_id: str,
    agent_run_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[Label]:
    """Get all labels for a specific agent run."""
    return await label_svc.get_labels_by_agent_run(agent_run_id)


###################
# Annotation CRUD #
###################


@label_router.post("/{collection_id}/annotation")
async def create_annotation(
    collection_id: str,
    request: CreateAnnotationRequest,
    label_svc: LabelService = Depends(get_label_service),
    user: User = Depends(get_user_anonymous_ok),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Create an annotation."""
    # Validate that the annotation's collection_id matches the path parameter
    logger.info(f"Creating annotation for user {user.email}")
    await label_svc.create_annotation(
        user.id,
        collection_id=collection_id,
        agent_run_id=request.agent_run_id,
        citations=request.citations,
        content=request.content,
    )
    return {"message": "Annotation created successfully"}


@label_router.put("/{collection_id}/annotation/{annotation_id}")
async def update_annotation(
    collection_id: str,
    annotation_id: str,
    request: UpdateAnnotationRequest,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Update an annotation."""
    # Verify that the annotation belongs to this collection
    annotation = await label_svc.get_annotation(annotation_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail=f"Annotation {annotation_id} not found")
    if annotation.collection_id != collection_id:
        raise HTTPException(
            status_code=404,
            detail=f"Annotation {annotation_id} not found in collection {collection_id}",
        )

    await label_svc.update_annotation(annotation_id, request.content)
    return {"message": "Annotation updated successfully"}


@label_router.delete("/{collection_id}/annotation/{annotation_id}")
async def delete_annotation(
    collection_id: str,
    annotation_id: str,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Delete an annotation."""
    # Verify that the annotation belongs to this collection
    annotation = await label_svc.get_annotation(annotation_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail=f"Annotation {annotation_id} not found")
    if annotation.collection_id != collection_id:
        raise HTTPException(
            status_code=404,
            detail=f"Annotation {annotation_id} not found in collection {collection_id}",
        )

    await label_svc.delete_annotation(annotation_id)
    return {"message": "Annotation deleted successfully"}


@label_router.get("/{collection_id}/agent_run/{agent_run_id}/annotations")
async def get_annotations_by_agent_run(
    collection_id: str,
    agent_run_id: str,
    label_svc: LabelService = Depends(get_label_service),
    mono_svc: MonoService = Depends(get_mono_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[Annotation]:
    """Get all annotations for a specific agent run."""
    # Verify that the agent run belongs to this collection
    try:
        await mono_svc.check_agent_run_in_collection(collection_id, agent_run_id)
    except LabelService.AgentRunCollectionMismatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return await label_svc.get_annotations_by_agent_run(agent_run_id)
