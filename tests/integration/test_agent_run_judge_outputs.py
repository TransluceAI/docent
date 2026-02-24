from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message
from docent.judges import JudgeResult, ResultType
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.rubric import SQLAJudgeResult
from docent_core.docent.services.monoservice import MonoService

JUDGE_MODEL = {
    "provider": "anthropic",
    "model_name": "claude-3-5-sonnet-20241022",
    "reasoning_effort": "low",
}

OUTPUT_SCHEMA = {"type": "object", "properties": {"label": {"type": "string"}}}


def make_agent_run() -> AgentRun:
    return AgentRun(
        id=str(uuid4()),
        transcripts=[
            Transcript(
                messages=[
                    parse_chat_message({"role": "user", "content": "Hi"}),
                    parse_chat_message({"role": "assistant", "content": "Hello"}),
                ]
            )
        ],
        metadata={"test": "agent_run_judge_outputs"},
    )


@pytest.mark.integration
async def test_agent_run_judge_outputs_returns_latest_version_per_rubric(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    agent_run = make_agent_run()
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=[agent_run])

    create_response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json={
            "rubric": {
                "rubric_text": "Judge rubric v1",
                "judge_model": JUDGE_MODEL,
                "output_schema": OUTPUT_SCHEMA,
            }
        },
    )
    assert create_response.status_code == 200
    rubric_id = create_response.json()

    db_session.add(
        SQLAJudgeResult.from_pydantic(
            JudgeResult(
                agent_run_id=agent_run.id,
                rubric_id=rubric_id,
                rubric_version=1,
                result_type=ResultType.DIRECT_RESULT,
                output={"label": "from-v1"},
            )
        )
    )

    update_response = await authed_client.put(
        f"/rest/rubric/{test_collection_id}/rubric/{rubric_id}",
        json={
            "rubric": {
                "id": rubric_id,
                "version": 2,
                "rubric_text": "Judge rubric v2",
                "judge_model": JUDGE_MODEL,
                "output_schema": OUTPUT_SCHEMA,
            }
        },
    )
    assert update_response.status_code == 200

    db_session.add(
        SQLAJudgeResult.from_pydantic(
            JudgeResult(
                agent_run_id=agent_run.id,
                rubric_id=rubric_id,
                rubric_version=2,
                result_type=ResultType.DIRECT_RESULT,
                output={"label": "from-v2"},
            )
        )
    )

    second_rubric_response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json={
            "rubric": {
                "rubric_text": "Second rubric v1",
                "judge_model": JUDGE_MODEL,
                "output_schema": OUTPUT_SCHEMA,
            }
        },
    )
    assert second_rubric_response.status_code == 200
    second_rubric_id = second_rubric_response.json()

    db_session.add(
        SQLAJudgeResult.from_pydantic(
            JudgeResult(
                agent_run_id=agent_run.id,
                rubric_id=second_rubric_id,
                rubric_version=1,
                result_type=ResultType.DIRECT_RESULT,
                output={"label": "second-v1"},
            )
        )
    )
    await db_session.commit()

    response = await authed_client.get(
        f"/rest/rubric/{test_collection_id}/agent_run/{agent_run.id}/judge_outputs"
    )
    assert response.status_code == 200
    grouped_outputs = response.json()

    by_rubric_id = {group["rubric_id"]: group for group in grouped_outputs}
    assert set(by_rubric_id) == {rubric_id, second_rubric_id}

    latest_group = by_rubric_id[rubric_id]
    assert latest_group["rubric_version"] == 2
    assert [result["output"]["label"] for result in latest_group["results"]] == ["from-v2"]

    second_group = by_rubric_id[second_rubric_id]
    assert second_group["rubric_version"] == 1
    assert [result["output"]["label"] for result in second_group["results"]] == ["second-v1"]
