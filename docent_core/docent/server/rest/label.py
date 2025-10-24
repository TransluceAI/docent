from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util.logger import get_logger
from docent.data_models.judge import Label
from docent_core.docent.db.schemas.label import LabelSet
from docent_core.docent.server.dependencies.database import get_session
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import get_label_service
from docent_core.docent.server.dependencies.user import get_user_anonymous_ok
from docent_core.docent.services.label import LabelService

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


################
# Label CRUD
################


@label_router.post("/{collection_id}/label")
async def create_label(
    collection_id: str,
    request: CreateLabelRequest,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Create a label."""
    await label_svc.create_label(request.label)
    return {"message": "Label created successfully"}


@label_router.post("/{collection_id}/labels")
async def create_labels(
    collection_id: str,
    request: CreateLabelsRequest,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Create multiple labels."""
    await label_svc.create_labels(request.labels)
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


####################
# Label Set CRUD
####################


@label_router.post("/{collection_id}/label_set")
async def create_label_set(
    collection_id: str,
    request: CreateLabelSetRequest,
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.WRITE)),
) -> dict[str, str]:
    """Create a label set."""
    label_set_id = await label_svc.create_label_set(
        request.name, request.label_schema, description=request.description
    )
    return {"label_set_id": label_set_id}


@label_router.get("/{collection_id}/label_set/{label_set_id}")
async def get_label_set(
    collection_id: str,
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
    label_sets = await label_svc.get_all_label_sets()
    return [ls.to_pydantic() for ls in label_sets]


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


@label_router.get("/{collection_id}/labels_in_label_sets")
async def get_labels_in_label_sets(
    collection_id: str,
    label_set_ids: list[str] = Query(alias="labelSetIds"),
    label_svc: LabelService = Depends(get_label_service),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> list[Label]:
    """Get all labels from multiple label sets."""
    return await label_svc.get_labels_in_label_sets(label_set_ids)


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
