import os
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Discriminator, Field, TypeAdapter
from sqlalchemy import select

from docent._log_util import get_logger
from docent_core._env_util import ENV
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.server.dependencies.user import get_user_anonymous_ok
from docent_core.docent.services.job import JobService
from docent_core.investigator.db.contexts import WorkspaceContext
from docent_core.investigator.db.schemas.experiment import (
    SQLACounterfactualExperimentResult,
)
from docent_core.investigator.services.counterfactual_service import CounterfactualService
from docent_core.investigator.services.monoservice import InvestigatorMonoService

logger = get_logger(__name__)

experiment_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


# Dependency to get InvestigatorMonoService
async def get_investigator_mono_svc() -> InvestigatorMonoService:
    """Get the InvestigatorMonoService instance."""
    return await InvestigatorMonoService.init()


async def get_counterfactual_service(
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
) -> CounterfactualService:
    """Get the CounterfactualService instance."""
    return CounterfactualService(investigator_svc)


async def get_authorized_investigator_user(
    user: User = Depends(get_user_anonymous_ok),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
) -> User:
    """Get user and verify they are authorized for investigator access."""
    if not await investigator_svc.is_user_authorized_for_investigator(user):
        raise HTTPException(
            status_code=403, detail="Access denied: User not authorized for investigator features"
        )
    return user


# =====================
# Workspace Models
# =====================


class CreateWorkspaceRequest(BaseModel):
    """Request model for creating a workspace."""

    name: Optional[str] = None
    description: Optional[str] = None


class WorkspaceResponse(BaseModel):
    """Response model for workspace."""

    id: str
    name: Optional[str]
    description: Optional[str]
    created_by: str
    created_at: str


# =====================
# Judge Config Models
# =====================


class CreateJudgeConfigRequest(BaseModel):
    """Request model for creating a judge config."""

    name: Optional[str] = None
    rubric: str


class JudgeConfigResponse(BaseModel):
    """Response model for judge config."""

    id: str
    name: Optional[str]
    rubric: str
    workspace_id: str
    created_at: str


# =====================
# Backend Config Models
# =====================


class CreateOpenAICompatibleBackendRequest(BaseModel):
    """Request model for creating an OpenAI-compatible backend config."""

    name: str
    provider: str  # openai, anthropic, google, custom
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class OpenAICompatibleBackendResponse(BaseModel):
    """Response model for OpenAI-compatible backend config."""

    id: str
    name: str
    provider: str
    model: str
    api_key: Optional[str]
    base_url: Optional[str]
    workspace_id: str
    created_at: str


# =====================
# Experiment Idea Models
# =====================


class CreateExperimentIdeaRequest(BaseModel):
    """Request model for creating an experiment idea."""

    name: str
    idea: str


class ExperimentIdeaResponse(BaseModel):
    """Response model for experiment idea."""

    id: str
    name: str
    idea: str
    workspace_id: str
    created_at: str


# =====================
# Base Interaction Models
# =====================


class ToolParameters(BaseModel):
    """JSON Schema format parameters for function tools."""

    type: Literal["object"] = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    additionalProperties: bool = False


class FunctionToolInfo(BaseModel):
    """Function tool that takes JSON schema parameters."""

    type: Literal["function"]
    name: str
    description: str
    parameters: ToolParameters
    strict: Optional[bool] = None


class CustomToolInfo(BaseModel):
    """Custom tool that processes any text input."""

    type: Literal["custom"]
    name: str
    description: str


# Union type with discriminator for automatic type selection
ToolInfo = Annotated[Union[FunctionToolInfo, CustomToolInfo], Discriminator("type")]


class CreateBaseContextRequest(BaseModel):
    """Request model for creating a base interaction."""

    name: str
    prompt: list[dict[str, Any]]  # List of messages with role, content, tool_calls, etc.
    tools: Optional[list[ToolInfo]] = None  # List of available tools


class BaseContextResponse(BaseModel):
    """Response model for base interaction."""

    id: str
    name: str
    prompt: list[dict[str, Any]]
    tools: Optional[list[ToolInfo]] = None
    workspace_id: str
    created_at: str


# =====================
# Experiment Config Models
# =====================


class CreateExperimentConfigRequest(BaseModel):
    """Request model for creating an experiment config."""

    judge_config_id: str
    openai_compatible_backend_id: str
    idea_id: str
    base_context_id: str
    num_counterfactuals: int = 1
    num_replicas: int = 1
    max_turns: int = 1


class ExperimentConfigResponse(BaseModel):
    """Response model for experiment config."""

    id: str
    workspace_id: str
    created_at: str
    judge_config_id: str
    openai_compatible_backend_id: str
    idea_id: str
    base_context_id: str
    num_counterfactuals: int
    num_replicas: int
    max_turns: int


# =====================
# Workspace Endpoints
# =====================


@experiment_router.post("/workspaces")
async def create_workspace(
    request: CreateWorkspaceRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Create a new investigator workspace."""
    workspace_id = await investigator_svc.create_workspace(
        user=user,
        name=request.name,
        description=request.description,
    )
    return {"id": workspace_id}


@experiment_router.get("/workspaces")
async def get_workspaces(
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """List all workspaces for the user."""
    workspaces = await investigator_svc.get_workspaces(user)
    return [
        WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            description=workspace.description,
            created_by=workspace.created_by,
            created_at=workspace.created_at.isoformat(),
        )
        for workspace in workspaces
    ]


@experiment_router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Get a single workspace by ID."""
    workspace = await investigator_svc.get_workspace(workspace_id)

    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check if user owns this workspace
    if workspace.created_by != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        created_by=workspace.created_by,
        created_at=workspace.created_at.isoformat(),
    )


@experiment_router.put("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    request: CreateWorkspaceRequest,  # Reuse the same request model
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Update a workspace's name and/or description."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Update the workspace
    updated = await investigator_svc.update_workspace(
        workspace_id=workspace_id,
        name=request.name,
        description=request.description,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {"message": "Workspace updated successfully"}


@experiment_router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Delete a workspace (cascades to all contained entities)."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    deleted = await investigator_svc.delete_workspace(workspace_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {"message": "Workspace deleted successfully"}


# =====================
# Judge Config Endpoints
# =====================


@experiment_router.post("/workspaces/{workspace_id}/judge-configs")
async def create_judge_config(
    workspace_id: str,
    request: CreateJudgeConfigRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Create a new judge config in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    judge_config_id = await investigator_svc.create_judge_config(
        workspace_id=workspace_id,
        name=request.name,
        rubric=request.rubric,
    )
    return {"id": judge_config_id}


@experiment_router.get("/workspaces/{workspace_id}/judge-configs")
async def get_judge_configs(
    workspace_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """List all judge configs in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    configs = await investigator_svc.get_judge_configs(workspace_id)
    return [
        JudgeConfigResponse(
            id=config.id,
            name=config.name,
            rubric=config.rubric,
            workspace_id=config.workspace_id,
            created_at=config.created_at.isoformat(),
        )
        for config in configs
    ]


@experiment_router.delete("/judge-configs/{judge_config_id}")
async def delete_judge_config(
    judge_config_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Delete a judge config."""
    judge_config = await investigator_svc.get_judge_config(judge_config_id)
    if judge_config is None:
        raise HTTPException(status_code=404, detail="Judge config not found")

    if not await investigator_svc.user_owns_workspace(user, judge_config.workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    deleted = await investigator_svc.delete_judge_config(judge_config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Judge config not found")
    return {"message": "Judge config deleted successfully"}


# =====================
# OpenAI Compatible Backend Endpoints
# =====================


@experiment_router.post("/workspaces/{workspace_id}/openai-compatible-backends")
async def create_openai_compatible_backend(
    workspace_id: str,
    request: CreateOpenAICompatibleBackendRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Create a new OpenAI-compatible backend config in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    backend_id = await investigator_svc.create_openai_compatible_backend(
        workspace_id=workspace_id,
        name=request.name,
        provider=request.provider,
        model=request.model,
        api_key=request.api_key,
        base_url=request.base_url,
    )
    return {"id": backend_id}


@experiment_router.get("/workspaces/{workspace_id}/openai-compatible-backends")
async def get_openai_compatible_backends(
    workspace_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """List all OpenAI-compatible backend configs in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    configs = await investigator_svc.get_openai_compatible_backends(workspace_id)
    return [
        OpenAICompatibleBackendResponse(
            id=config.id,
            name=config.name,
            provider=config.provider,
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            workspace_id=config.workspace_id,
            created_at=config.created_at.isoformat(),
        )
        for config in configs
    ]


@experiment_router.delete("/openai-compatible-backends/{backend_id}")
async def delete_openai_compatible_backend(
    backend_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Delete an OpenAI-compatible backend config."""
    backend = await investigator_svc.get_openai_compatible_backend(backend_id)
    if backend is None:
        raise HTTPException(status_code=404, detail="OpenAI-compatible backend not found")

    if not await investigator_svc.user_owns_workspace(user, backend.workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    deleted = await investigator_svc.delete_openai_compatible_backend(backend_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="OpenAI-compatible backend not found")
    return {"message": "OpenAI-compatible backend deleted successfully"}


class ListModelsRequest(BaseModel):
    """Request model for listing available models."""

    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


@experiment_router.post("/openai-compatible-backends/list-models")
async def list_available_models(
    request: ListModelsRequest,
    user: User = Depends(get_authorized_investigator_user),
) -> dict[str, list[str]]:
    """List available models for a given provider configuration."""
    try:
        # Set default base URLs based on provider
        base_url = request.base_url
        api_key = request.api_key
        if request.provider == "openai":
            base_url = base_url or "https://api.openai.com/v1/"
            api_key = os.getenv("OPENAI_API_KEY")
        elif request.provider == "anthropic":
            base_url = base_url or "https://api.anthropic.com/v1/"
            api_key = os.getenv("ANTHROPIC_API_KEY")
        elif request.provider == "google":
            base_url = base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
            api_key = os.getenv("GOOGLE_API_KEY")
        elif request.provider == "custom":
            if not base_url:
                raise HTTPException(
                    status_code=400, detail="Base URL is required for custom provider"
                )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {request.provider}")

        # Create OpenAI client with the configuration
        client = AsyncOpenAI(
            api_key=api_key
            or "dummy-key",  # Some providers don't require API key for listing models
            base_url=base_url,
        )

        # List available models
        models = await client.models.list()

        # Extract model names
        model_names = [model.id for model in models.data]

        return {"models": model_names}
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        # Return empty list if there's an error (e.g., invalid credentials)
        return {"models": []}


# =====================
# Experiment Idea Endpoints
# =====================


@experiment_router.post("/workspaces/{workspace_id}/experiment-ideas")
async def create_experiment_idea(
    workspace_id: str,
    request: CreateExperimentIdeaRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Create a new experiment idea in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    idea_id = await investigator_svc.create_experiment_idea(
        workspace_id=workspace_id,
        name=request.name,
        idea=request.idea,
    )
    return {"id": idea_id}


@experiment_router.get("/workspaces/{workspace_id}/experiment-ideas")
async def get_experiment_ideas(
    workspace_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """List all experiment ideas in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    ideas = await investigator_svc.get_experiment_ideas(workspace_id)
    return [
        ExperimentIdeaResponse(
            id=idea.id,
            name=idea.name,
            idea=idea.idea,
            workspace_id=idea.workspace_id,
            created_at=idea.created_at.isoformat(),
        )
        for idea in ideas
    ]


@experiment_router.delete("/experiment-ideas/{idea_id}")
async def delete_experiment_idea(
    idea_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Delete an experiment idea."""
    idea = await investigator_svc.get_experiment_idea(idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Experiment idea not found")

    if not await investigator_svc.user_owns_workspace(user, idea.workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    deleted = await investigator_svc.delete_experiment_idea(idea_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Experiment idea not found")
    return {"message": "Experiment idea deleted successfully"}


# =====================
# Base Interaction Endpoints
# =====================


@experiment_router.post("/workspaces/{workspace_id}/base-contexts")
async def create_base_context(
    workspace_id: str,
    request: CreateBaseContextRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Create a new base interaction in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    tools_dict = None
    if request.tools:
        tools_dict = [tool.model_dump(exclude_none=True) for tool in request.tools]
        logger.debug(f"Creating base context with {len(request.tools)} tools")
        logger.debug(f"Tools data: {tools_dict}")

    interaction_id = await investigator_svc.create_base_context(
        workspace_id=workspace_id,
        name=request.name,
        prompt=request.prompt,
        tools=tools_dict,
    )
    return {"id": interaction_id}


@experiment_router.get("/workspaces/{workspace_id}/base-contexts")
async def get_base_contexts(
    workspace_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """List all base interactions in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    interactions = await investigator_svc.get_base_contexts(workspace_id)

    # TypeAdapter for parsing tools with discriminated union
    tool_adapter: TypeAdapter[ToolInfo] = TypeAdapter(ToolInfo)

    responses: list[BaseContextResponse] = []
    for interaction in interactions:
        tools: Optional[list[ToolInfo]] = None
        if interaction.tools:
            tools = []
            for tool_dict in interaction.tools:
                try:
                    # Pydantic automatically selects the right type based on the "type" field
                    tool = tool_adapter.validate_python(tool_dict)
                    tools.append(tool)
                except Exception as e:
                    logger.error(
                        f"Failed to parse tool {tool_dict.get('name', 'unknown')} for interaction {interaction.id}: {e}"
                    )
                    # Skip invalid tools rather than failing the whole response

        responses.append(
            BaseContextResponse(
                id=interaction.id,
                name=interaction.name,
                prompt=interaction.prompt,
                tools=tools,
                workspace_id=interaction.workspace_id,
                created_at=interaction.created_at.isoformat(),
            )
        )

    return responses


@experiment_router.delete("/base-contexts/{interaction_id}")
async def delete_base_context(
    interaction_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Delete a base interaction."""
    base_context = await investigator_svc.get_base_context(interaction_id)
    if base_context is None:
        raise HTTPException(status_code=404, detail="Base interaction not found")

    if not await investigator_svc.user_owns_workspace(user, base_context.workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    deleted = await investigator_svc.delete_base_context(interaction_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Base interaction not found")
    return {"message": "Base interaction deleted successfully"}


# =====================
# Experiment Config Endpoints
# =====================


@experiment_router.post("/workspaces/{workspace_id}/experiment-configs")
async def create_experiment_config(
    workspace_id: str,
    request: CreateExperimentConfigRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Create a new experiment config in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Validate experiment configuration limits
    if request.num_counterfactuals > 64:
        raise HTTPException(
            status_code=400,
            detail=f"Number of counterfactuals ({request.num_counterfactuals}) exceeds maximum of 64",
        )

    if request.num_replicas > 256:
        raise HTTPException(
            status_code=400,
            detail=f"Number of replicas ({request.num_replicas}) exceeds maximum of 256",
        )

    # Total rollouts includes base context + counterfactuals, all multiplied by replicas
    total_rollouts = (request.num_counterfactuals + 1) * request.num_replicas
    if total_rollouts > 1024:
        raise HTTPException(
            status_code=400,
            detail=f"Total rollouts (({request.num_counterfactuals} + 1) × {request.num_replicas} = {total_rollouts}) exceeds maximum of 1024",
        )

    experiment_config_id = await investigator_svc.create_experiment_config(
        workspace_id=workspace_id,
        judge_config_id=request.judge_config_id,
        openai_compatible_backend_id=request.openai_compatible_backend_id,
        idea_id=request.idea_id,
        base_context_id=request.base_context_id,
        num_counterfactuals=request.num_counterfactuals,
        num_replicas=request.num_replicas,
        max_turns=request.max_turns,
    )
    return {"id": experiment_config_id}


@experiment_router.get("/workspaces/{workspace_id}/experiment-configs")
async def get_experiment_configs(
    workspace_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """List all experiment configs in a workspace."""
    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    configs = await investigator_svc.get_experiment_configs(workspace_id)
    return [
        ExperimentConfigResponse(
            id=config.id,
            workspace_id=config.workspace_id,
            created_at=config.created_at.isoformat(),
            judge_config_id=config.judge_config_id,
            openai_compatible_backend_id=config.openai_compatible_backend_id,
            idea_id=config.idea_id,
            base_context_id=config.base_context_id,
            num_counterfactuals=config.num_counterfactuals,
            num_replicas=config.num_replicas,
            max_turns=config.max_turns,
        )
        for config in configs
    ]


@experiment_router.get("/experiment-configs/{experiment_config_id}")
async def get_experiment_config(
    experiment_config_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Get a single experiment config by ID."""
    config = await investigator_svc.get_experiment_config(experiment_config_id)

    if config is None:
        raise HTTPException(status_code=404, detail="Experiment config not found")

    # Check if user owns the workspace that contains this config
    workspace = await investigator_svc.get_workspace(config.workspace_id)
    if workspace and workspace.created_by != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return ExperimentConfigResponse(
        id=config.id,
        workspace_id=config.workspace_id,
        created_at=config.created_at.isoformat(),
        judge_config_id=config.judge_config_id,
        openai_compatible_backend_id=config.openai_compatible_backend_id,
        idea_id=config.idea_id,
        base_context_id=config.base_context_id,
        num_counterfactuals=config.num_counterfactuals,
        num_replicas=config.num_replicas,
        max_turns=config.max_turns,
    )


@experiment_router.delete("/experiment-configs/{experiment_config_id}")
async def delete_experiment_config(
    experiment_config_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Delete an experiment config."""
    # First check if the config exists
    config = await investigator_svc.get_experiment_config(experiment_config_id)

    if config is None:
        raise HTTPException(status_code=404, detail="Experiment config not found")

    # Check if user owns the workspace that contains this config
    if not await investigator_svc.user_owns_workspace(user, config.workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    deleted = await investigator_svc.delete_experiment_config(experiment_config_id)

    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete experiment config")

    return {"message": "Experiment config deleted successfully"}


# =====================
# Experiment Execution
# =====================


@experiment_router.post("/{workspace_id}/experiment/{experiment_config_id}/run")
async def start_experiment(
    workspace_id: str,
    experiment_config_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Start running a counterfactual experiment."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify the experiment config exists and belongs to the workspace
    configs = await investigator_svc.get_experiment_configs(workspace_id)
    if not any(c.id == experiment_config_id for c in configs):
        raise HTTPException(
            status_code=404,
            detail=f"Experiment config {experiment_config_id} not found in workspace {workspace_id}",
        )

    ctx = WorkspaceContext(
        workspace_id=workspace_id,
        user=user,
        base_filter=None,
    )

    # Start or get existing job
    job_id = await counterfactual_svc.start_or_get_experiment_job(ctx, experiment_config_id)

    logger.info(f"Started experiment job {job_id} for config {experiment_config_id}")

    return {"job_id": job_id, "experiment_config_id": experiment_config_id}


@experiment_router.post("/{workspace_id}/experiment/{experiment_config_id}/cancel")
async def cancel_experiment(
    workspace_id: str,
    experiment_config_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Cancel a running counterfactual experiment."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify the experiment config exists and belongs to the workspace
    configs = await investigator_svc.get_experiment_configs(workspace_id)
    if not any(c.id == experiment_config_id for c in configs):
        raise HTTPException(
            status_code=404,
            detail=f"Experiment config {experiment_config_id} not found in workspace {workspace_id}",
        )

    # Get active job for this experiment
    active_job = await counterfactual_svc.get_active_experiment_job(experiment_config_id)

    if not active_job:
        raise HTTPException(
            status_code=404,
            detail=f"No active job found for experiment {experiment_config_id}",
        )

    # we cancel the job directly instead of trying to cancel it gracefully using the job service
    async with investigator_svc.db.session() as session:
        job_svc = JobService(session, investigator_svc.db.session)
        await job_svc.cancel_job(active_job.id)

    # Save minimal cancelled experiment result
    async with investigator_svc.db.session() as session:
        existing = await session.execute(
            select(SQLACounterfactualExperimentResult).where(
                SQLACounterfactualExperimentResult.experiment_config_id == experiment_config_id
            )
        )
        sqla_result = existing.scalar_one_or_none()

        now = datetime.now(UTC).replace(tzinfo=None)

        if sqla_result:
            sqla_result.status = "cancelled"
            sqla_result.completed_at = now
        else:
            session.add(
                SQLACounterfactualExperimentResult(
                    id=str(uuid4()),
                    experiment_config_id=experiment_config_id,
                    collection_id=None,
                    status="cancelled",
                    progress=0,
                    agent_run_metadata=None,
                    counterfactual_idea_output=None,
                    counterfactual_context_output=None,
                    parsed_counterfactual_ideas=None,
                    counterfactual_policy_configs=None,
                    base_policy_config=None,
                    completed_at=now,
                )
            )

        await session.commit()

    logger.info(f"Cancelled experiment job {active_job.id} for config {experiment_config_id}")

    return {"message": "Experiment cancelled successfully", "job_id": active_job.id}


@experiment_router.get("/{workspace_id}/experiment/job/{job_id}/listen")
async def listen_to_experiment_job(
    workspace_id: str,
    job_id: str,
    user: User = Depends(get_user_anonymous_ok),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Stream experiment state updates via Server-Sent Events."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    logger.info(f"Client listening to experiment job {job_id}")

    async def event_generator():
        """Generate SSE events from the job state stream."""
        try:
            async for state in counterfactual_svc.listen_for_job_state(job_id):
                # Format as Server-Sent Event
                yield f"data: {state.model_dump_json()}\n\n"
        except Exception as e:
            logger.error(f"Error streaming job {job_id}: {e}")
            yield f'data: {{"error": "An error occurred while streaming experiment data"}}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "Connection": "keep-alive",
        },
    )


@experiment_router.get("/{workspace_id}/active-jobs")
async def get_active_experiment_jobs(
    workspace_id: str,
    user: User = Depends(get_user_anonymous_ok),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
) -> dict[str, dict[str, Optional[str]]]:
    """Get all active jobs for experiments in a workspace."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Get all experiment configs for the workspace
    configs = await investigator_svc.get_experiment_configs(workspace_id)

    # Build a map of experiment_config_id -> active job info
    active_jobs_map: dict[str, dict[str, Optional[str]]] = {}

    for config in configs:
        active_job = await counterfactual_svc.get_active_experiment_job(config.id)

        if active_job:
            active_jobs_map[config.id] = {
                "job_id": active_job.id,
                "status": active_job.status.value,
            }
        else:
            active_jobs_map[config.id] = {
                "job_id": None,
                "status": None,
            }

    return active_jobs_map


@experiment_router.get("/{workspace_id}/experiment/{experiment_config_id}/active-job")
async def get_active_experiment_job(
    workspace_id: str,
    experiment_config_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """
    Get the active job for an experiment config, if any.

    DEPRECATED: Use GET /{workspace_id}/active-jobs instead to fetch all active jobs at once.
    This endpoint will be removed in a future version.
    """

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify the experiment config exists and belongs to the workspace
    configs = await investigator_svc.get_experiment_configs(workspace_id)
    if not any(c.id == experiment_config_id for c in configs):
        raise HTTPException(
            status_code=404,
            detail=f"Experiment config {experiment_config_id} not found in workspace {workspace_id}",
        )

    # Get active job if it exists
    active_job = await counterfactual_svc.get_active_experiment_job(experiment_config_id)

    if active_job:
        return {
            "job_id": active_job.id,
            "experiment_config_id": experiment_config_id,
            "status": active_job.status.value,
        }
    else:
        return {
            "job_id": None,
            "experiment_config_id": experiment_config_id,
            "status": None,
        }


@experiment_router.get("/{workspace_id}/experiment/{experiment_config_id}/result")
async def get_experiment_result(
    workspace_id: str,
    experiment_config_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Get the experiment result - either from active job (Redis) or stored result (database)."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify the experiment config exists and belongs to the workspace
    configs = await investigator_svc.get_experiment_configs(workspace_id)
    if not any(c.id == experiment_config_id for c in configs):
        raise HTTPException(
            status_code=404,
            detail=f"Experiment config {experiment_config_id} not found in workspace {workspace_id}",
        )

    # First check if there's an active job for this experiment
    active_job = await counterfactual_svc.get_active_experiment_job(experiment_config_id)

    if active_job:
        # Get the current state from Redis for the active job
        summary = await counterfactual_svc.get_job_state_from_redis(active_job.id)
        if summary is not None:
            return summary.model_dump()

    # No active job or no Redis state, try to get the stored result from database
    result = await counterfactual_svc.get_experiment_result(
        experiment_config_id, include_agent_runs=False, user=user
    )

    if result is None:
        return None

    # Return the summary (lightweight version for streaming)
    return result.summary().model_dump()


@experiment_router.get("/{workspace_id}/experiment/job/{job_id}/status")
async def get_experiment_job_status(
    workspace_id: str,
    job_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Get the current status of an experiment job."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    job = await counterfactual_svc.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return {
        "job_id": job.id,
        "status": job.status.value,
        "type": job.type,
        "metadata": job.job_json,
    }


@experiment_router.get("/{workspace_id}/experiment/{experiment_config_id}/agent-run/{agent_run_id}")
async def get_experiment_agent_run(
    workspace_id: str,
    experiment_config_id: str,
    agent_run_id: str,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Get a single agent run from an experiment result."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify the experiment config exists and belongs to the workspace
    configs = await investigator_svc.get_experiment_configs(workspace_id)
    if not any(c.id == experiment_config_id for c in configs):
        raise HTTPException(
            status_code=404,
            detail=f"Experiment config {experiment_config_id} not found in workspace {workspace_id}",
        )

    # Get the agent run from the result
    agent_run = await counterfactual_svc.get_experiment_agent_run(
        experiment_config_id, agent_run_id, user
    )

    if agent_run is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent run {agent_run_id} not found for experiment {experiment_config_id}",
        )

    return agent_run


class SubscribeAgentRunRequest(BaseModel):
    """Request model for subscribing to an agent run."""

    agent_run_id: str


@experiment_router.post("/{workspace_id}/experiment/job/{job_id}/subscribe-agent-run")
async def subscribe_to_agent_run(
    workspace_id: str,
    job_id: str,
    request: SubscribeAgentRunRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Subscribe to receive full agent run data through the experiment SSE stream."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify the job exists
    job = await counterfactual_svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Add the agent run to the subscription set
    # TODO(neil): move this to the counterfactual service
    from docent_core._server._broker.redis_client import get_redis_client

    REDIS = await get_redis_client()
    await REDIS.sadd(f"agent_run:subscriptions:{job_id}", request.agent_run_id)  # type: ignore

    logger.info(f"Subscribed to agent run {request.agent_run_id} for job {job_id}")

    return {"subscribed": request.agent_run_id, "job_id": job_id}


@experiment_router.post("/{workspace_id}/experiment/job/{job_id}/unsubscribe-agent-run")
async def unsubscribe_from_agent_run(
    workspace_id: str,
    job_id: str,
    request: SubscribeAgentRunRequest,
    user: User = Depends(get_authorized_investigator_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
    counterfactual_svc: CounterfactualService = Depends(get_counterfactual_service),
):
    """Unsubscribe from receiving full agent run data through the experiment SSE stream."""

    # Check if user owns this workspace
    if not await investigator_svc.user_owns_workspace(user, workspace_id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Verify the job exists
    job = await counterfactual_svc.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Remove the agent run from the subscription set
    # TODO(neil): move this to the counterfactual service
    from docent_core._server._broker.redis_client import get_redis_client

    REDIS = await get_redis_client()
    await REDIS.srem(f"agent_run:subscriptions:{job_id}", request.agent_run_id)  # type: ignore

    logger.info(f"Unsubscribed from agent run {request.agent_run_id} for job {job_id}")

    return {"unsubscribed": request.agent_run_id, "job_id": job_id}


# =====================
# =====================


class AuthorizedUserResponse(BaseModel):
    user_id: str
    email: str
    created_at: str


class AddAuthorizedUserRequest(BaseModel):
    email: str


# Get admin emails from environment variable
# Environment variable should be a comma-separated list of emails
def _get_investigator_admin_emails() -> list[str]:
    """Get the investigator admin emails from environment or defaults."""
    env_admin_emails = ENV.get("INVESTIGATOR_ADMIN_EMAILS")
    if env_admin_emails:
        # Parse comma-separated list and strip whitespace from each email
        emails = [email.strip() for email in env_admin_emails.split(",") if email.strip()]
        logger.info(f"Loaded {len(emails)} investigator admin emails from environment variable")
        return emails
    else:
        logger.info("No investigator admin emails found in environment variable, using empty list")
        return []


INVESTIGATOR_ADMIN_EMAILS = _get_investigator_admin_emails()


async def get_investigator_admin_user(
    user: User = Depends(get_authorized_investigator_user),
) -> User:
    """Get user and verify they are an investigator admin."""
    if user.email not in INVESTIGATOR_ADMIN_EMAILS:
        raise HTTPException(
            status_code=403,
            detail="Access denied: User not authorized for investigator admin features",
        )
    return user


# =====================
# Admin Endpoints
# =====================


@experiment_router.get("/admin/authorized-users")
async def get_authorized_users(
    admin_user: User = Depends(get_investigator_admin_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Get list of all authorized investigator users."""
    return await investigator_svc.get_all_authorized_users()


@experiment_router.post("/admin/authorized-users")
async def add_authorized_user(
    request: AddAuthorizedUserRequest,
    admin_user: User = Depends(get_investigator_admin_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Add a user to the investigator authorized users list by email."""
    success = await investigator_svc.add_authorized_user_by_email(request.email)
    if not success:
        raise HTTPException(status_code=400, detail="User not found or already authorized")
    return {"message": "User added successfully"}


@experiment_router.delete("/admin/authorized-users/{user_id}")
async def remove_authorized_user(
    user_id: str,
    admin_user: User = Depends(get_investigator_admin_user),
    investigator_svc: InvestigatorMonoService = Depends(get_investigator_mono_svc),
):
    """Remove a user from the investigator authorized users list."""
    success = await investigator_svc.remove_authorized_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found in authorized list")
    return {"message": "User removed successfully"}
