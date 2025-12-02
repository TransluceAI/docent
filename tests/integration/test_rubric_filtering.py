from typing import Any
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

transcript_raw = [
    {"role": "user", "content": "What's the weather like in New York today?"},
    {
        "role": "assistant",
        "content": "The weather in New York today is mostly sunny with a high of 75°F (24°C).",
    },
]


def runs_with_metadata(metadatas: list[dict[str, Any]]) -> list[AgentRun]:
    return [
        AgentRun(
            id=str(uuid4()),
            transcripts=[Transcript(messages=[parse_chat_message(msg) for msg in transcript_raw])],
            metadata=metadata,
        )
        for metadata in metadatas
    ]


@pytest.mark.integration
async def test_filter_by_rubric_output(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test filtering judge results by rubric output fields."""
    metadata_1 = {"test_id": "run1"}
    metadata_2 = {"test_id": "run2"}
    metadata_3 = {"test_id": "run3"}

    agent_runs = runs_with_metadata([metadata_1, metadata_2, metadata_3])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    rubric_payload = {
        "rubric": {
            "rubric_text": "Rate the quality of the response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "score": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 10,
                        "description": "Quality score from 0-10",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["excellent", "good", "poor"],
                    },
                },
            },
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json=rubric_payload,
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for i, agent_run_id in enumerate(agent_run_ids):
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"score": (i + 1) * 3, "category": ["poor", "good", "excellent"][i]},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": None},
    )
    assert response.status_code == 200
    all_results = response.json()["results"]
    assert len(all_results) == 3

    filter_dict = {
        "type": "primitive",
        "key_path": ["rubric", rubric_id, "score"],
        "value": 6,
        "op": ">",
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 1
    assert filtered_results[0]["results"][0]["output"]["score"] == 9

    filter_dict = {
        "type": "primitive",
        "key_path": ["rubric", rubric_id, "category"],
        "value": "excellent",
        "op": "==",
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 1
    assert filtered_results[0]["results"][0]["output"]["category"] == "excellent"


@pytest.mark.integration
async def test_filter_by_metadata(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test filtering judge results by agent run metadata."""
    metadata_1 = {"env": "prod", "version": 1}
    metadata_2 = {"env": "staging", "version": 2}
    metadata_3 = {"env": "prod", "version": 2}

    agent_runs = runs_with_metadata([metadata_1, metadata_2, metadata_3])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                },
            },
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json=rubric_payload,
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for agent_run_id in agent_run_ids:
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"label": "test"},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    filter_dict = {
        "type": "primitive",
        "key_path": ["metadata", "env"],
        "value": "prod",
        "op": "==",
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 2


@pytest.mark.integration
async def test_filter_by_agent_run_id(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test filtering judge results by agent_run_id."""
    agent_runs = runs_with_metadata([{"test": "a"}, {"test": "b"}, {"test": "c"}])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                },
            },
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json=rubric_payload,
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for agent_run_id in agent_run_ids:
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"label": "test"},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    target_agent_run_id = agent_run_ids[1]
    filter_dict = {
        "type": "primitive",
        "key_path": ["agent_run_id"],
        "value": target_agent_run_id,
        "op": "==",
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 1
    assert filtered_results[0]["agent_run_id"] == target_agent_run_id


@pytest.mark.integration
async def test_filter_by_tag(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test filtering judge results by tag."""
    agent_runs = runs_with_metadata([{"test": "a"}, {"test": "b"}, {"test": "c"}])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    # Tag the first and third agent runs
    for agent_run_id in [agent_run_ids[0], agent_run_ids[2]]:
        response = await authed_client.post(
            f"/rest/label/{test_collection_id}/tag",
            json={"agent_run_id": agent_run_id, "value": "priority"},
        )
        assert response.status_code == 200

    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                },
            },
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json=rubric_payload,
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for agent_run_id in agent_run_ids:
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"label": "test"},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    filter_dict = {
        "type": "primitive",
        "key_path": ["tag"],
        "value": "priority",
        "op": "==",
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 2
    result_agent_run_ids = {r["agent_run_id"] for r in filtered_results}
    assert result_agent_run_ids == {agent_run_ids[0], agent_run_ids[2]}


@pytest.mark.integration
async def test_complex_filter(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test complex filters combining rubric output and metadata."""
    metadata_1 = {"env": "prod", "priority": 1}
    metadata_2 = {"env": "prod", "priority": 2}
    metadata_3 = {"env": "staging", "priority": 1}

    agent_runs = runs_with_metadata([metadata_1, metadata_2, metadata_3])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    rubric_payload = {
        "rubric": {
            "rubric_text": "Rate the response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 0, "maximum": 10},
                },
            },
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json=rubric_payload,
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for i, agent_run_id in enumerate(agent_run_ids):
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"score": [8, 5, 7][i]},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    filter_dict = {
        "type": "complex",
        "op": "and",
        "filters": [
            {
                "type": "primitive",
                "key_path": ["metadata", "env"],
                "value": "prod",
                "op": "==",
            },
            {
                "type": "primitive",
                "key_path": ["rubric", rubric_id, "score"],
                "value": 6,
                "op": ">",
            },
        ],
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 1
    assert filtered_results[0]["results"][0]["output"]["score"] == 8


@pytest.mark.integration
async def test_no_duplicates_with_tags(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test that filtering never returns duplicates when agent runs have multiple tags.

    Tests two scenarios:
    1. Metadata-only filter (tests conditional tag join optimization)
    2. Tag OR filter (tests DISTINCT deduplication)
    """
    agent_runs = runs_with_metadata([{"env": "prod"}, {"env": "staging"}])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    # Add multiple tags to both agent runs
    for agent_run_id in agent_run_ids:
        for tag_value in ["priority", "urgent", "bug"]:
            response = await authed_client.post(
                f"/rest/label/{test_collection_id}/tag",
                json={"agent_run_id": agent_run_id, "value": tag_value},
            )
            assert response.status_code == 200

    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                },
            },
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json=rubric_payload,
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for agent_run_id in agent_run_ids:
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"label": "test"},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    # Scenario 1: Filter by metadata only (not tags)
    # Without conditional join optimization, would unnecessarily join tags
    filter_dict = {
        "type": "primitive",
        "key_path": ["metadata", "env"],
        "value": "prod",
        "op": "==",
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 1
    assert filtered_results[0]["agent_run_id"] == agent_run_ids[0]
    assert len(filtered_results[0]["results"]) == 1

    # Scenario 2: Filter by tags with OR - matches 2 of 3 tags
    # Without DISTINCT, would return duplicate results
    filter_dict = {
        "type": "complex",
        "op": "or",
        "filters": [
            {
                "type": "primitive",
                "key_path": ["tag"],
                "value": "priority",
                "op": "==",
            },
            {
                "type": "primitive",
                "key_path": ["tag"],
                "value": "urgent",
                "op": "==",
            },
        ],
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    # Both agent runs have both matching tags, should return 2 results (not 4 duplicates)
    assert len(filtered_results) == 2
    for agent_run_result in filtered_results:
        assert len(agent_run_result["results"]) == 1


@pytest.mark.integration
async def test_agent_run_id_filter_type(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test the AgentRunIdFilter type with a list of agent run IDs."""
    agent_runs = runs_with_metadata([{"test": "a"}, {"test": "b"}, {"test": "c"}])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}},
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric", json=rubric_payload
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for agent_run_id in agent_run_ids:
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"label": "test"},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    filter_dict = {"type": "agent_run_id", "agent_run_ids": [agent_run_ids[0], agent_run_ids[2]]}
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 2
    result_ids = {r["agent_run_id"] for r in filtered_results}
    assert result_ids == {agent_run_ids[0], agent_run_ids[2]}


@pytest.mark.integration
async def test_filter_by_created_at(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test filtering judge results by created_at timestamp."""
    from sqlalchemy import select

    from docent_core.docent.db.schemas.tables import SQLAAgentRun

    agent_runs = runs_with_metadata([{"order": 1}, {"order": 2}, {"order": 3}])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    # Query DB to get actual created_at timestamps
    result = await db_session.execute(
        select(SQLAAgentRun.id, SQLAAgentRun.created_at).where(SQLAAgentRun.id.in_(agent_run_ids))
    )
    timestamps = {row[0]: row[1] for row in result.all()}
    middle_timestamp = str(timestamps[agent_run_ids[1]])

    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}},
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric", json=rubric_payload
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for agent_run_id in agent_run_ids:
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"label": "test"},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    filter_dict = {
        "type": "primitive",
        "key_path": ["created_at"],
        "value": middle_timestamp,
        "op": ">=",
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) >= 2
    result_ids = {r["agent_run_id"] for r in filtered_results}
    assert agent_run_ids[1] in result_ids


@pytest.mark.integration
async def test_filter_tag_and_metadata(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
    db_session: AsyncSession,
):
    """Test complex AND filter combining tags with metadata (validates DISTINCT logic)."""
    agent_runs = runs_with_metadata([{"env": "prod"}, {"env": "staging"}, {"env": "prod"}])
    agent_run_ids = [run.id for run in agent_runs]

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    # Tag only the first and third runs (both prod)
    for agent_run_id in [agent_run_ids[0], agent_run_ids[2]]:
        response = await authed_client.post(
            f"/rest/label/{test_collection_id}/tag",
            json={"agent_run_id": agent_run_id, "value": "priority"},
        )
        assert response.status_code == 200

    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}},
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric", json=rubric_payload
    )
    assert response.status_code == 200
    rubric_id = response.json()

    for agent_run_id in agent_run_ids:
        result = JudgeResult(
            agent_run_id=agent_run_id,
            rubric_id=rubric_id,
            rubric_version=1,
            result_type=ResultType.DIRECT_RESULT,
            output={"label": "test"},
        )
        db_session.add(SQLAJudgeResult.from_pydantic(result))
    await db_session.commit()

    filter_dict = {
        "type": "complex",
        "op": "and",
        "filters": [
            {"type": "primitive", "key_path": ["tag"], "value": "priority", "op": "=="},
            {"type": "primitive", "key_path": ["metadata", "env"], "value": "prod", "op": "=="},
        ],
    }
    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/{rubric_id}/rubric_run_state",
        json={"filter_dict": filter_dict},
    )
    assert response.status_code == 200
    filtered_results = response.json()["results"]
    assert len(filtered_results) == 2
    result_ids = {r["agent_run_id"] for r in filtered_results}
    assert result_ids == {agent_run_ids[0], agent_run_ids[2]}
