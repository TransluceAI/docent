from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from docent._log_util.logger import get_logger
from docent_core.docent.ai_tools.rubric.elicit import (
    ElicitedQuestion,
    deduplicate_and_select_questions,
    extract_questions_from_agent_runs,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.server.dependencies.permissions import (
    Permission,
    require_collection_permission,
)
from docent_core.docent.server.dependencies.services import (
    get_llm_svc,
    get_mono_svc,
)
from docent_core.docent.server.dependencies.user import (
    get_default_view_ctx,
    get_user_anonymous_ok,
)
from docent_core.docent.services.llms import LLMService
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)

qa_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


class QaRubricElicitationRequest(BaseModel):
    rubric_description: str
    num_samples: int = Field(default=50, ge=1)
    top_k: int = Field(default=10, ge=1)

    class Config:
        extra = "forbid"


class QaRubricElicitationResponse(BaseModel):
    questions: list[ElicitedQuestion]
    sampled_agent_run_ids: list[str]


@qa_router.post(
    "/{collection_id}/rubric-elicitation",
    response_model=QaRubricElicitationResponse,
)
async def run_rubric_elicitation(
    collection_id: str,
    request: QaRubricElicitationRequest,
    ctx: ViewContext = Depends(get_default_view_ctx),
    mono_svc: MonoService = Depends(get_mono_svc),
    llm_svc: LLMService = Depends(get_llm_svc),
    _: None = Depends(require_collection_permission(Permission.READ)),
) -> QaRubricElicitationResponse:
    logger.info(
        f"Starting rubric elicitation for collection {collection_id} "
        f"(num_samples={request.num_samples}, top_k={request.top_k})"
    )
    agent_run_ids = await mono_svc.get_agent_run_ids(ctx)
    if not agent_run_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Collection {collection_id} has no agent runs",
        )

    logger.info(f"Found {len(agent_run_ids)} total agent runs in collection")
    if len(agent_run_ids) <= request.num_samples:
        sampled_ids = list(agent_run_ids)
        random.shuffle(sampled_ids)
    else:
        sampled_ids = random.sample(agent_run_ids, request.num_samples)
    logger.info(f"Sampled {len(sampled_ids)} agent runs for analysis")

    agent_runs = await mono_svc.get_agent_runs(ctx, agent_run_ids=sampled_ids)
    agent_run_map = {run.id: run for run in agent_runs}
    ordered_agent_runs = [
        agent_run_map[run_id] for run_id in sampled_ids if run_id in agent_run_map
    ]
    logger.info(f"Loaded {len(ordered_agent_runs)} agent runs successfully")

    if not ordered_agent_runs:
        raise HTTPException(
            status_code=404,
            detail="No sampled agent runs could be loaded",
        )

    rubric_description = request.rubric_description.strip()
    if not rubric_description:
        raise HTTPException(
            status_code=400,
            detail="rubric_description must not be empty",
        )
    all_questions = await extract_questions_from_agent_runs(
        agent_runs=ordered_agent_runs,
        rubric_description=rubric_description,
        llm_svc=llm_svc,
        max_questions_per_run=3,
    )

    selected_questions, _metadata = await deduplicate_and_select_questions(
        questions=all_questions,
        llm_svc=llm_svc,
        rubric_description=rubric_description,
        max_questions=request.top_k,  # Keep request field name for backward compat
    )

    logger.info(
        f"Rubric elicitation complete: returning {len(selected_questions)} questions "
        f"from {len(sampled_ids)} sampled runs"
    )
    return QaRubricElicitationResponse(
        questions=selected_questions,
        sampled_agent_run_ids=sampled_ids,
    )
