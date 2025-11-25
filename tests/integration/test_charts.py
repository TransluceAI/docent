from typing import Any

import httpx
import pytest

from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message
from docent_core.docent.db.schemas.auth_models import User
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
            transcripts=[Transcript(messages=[parse_chat_message(msg) for msg in transcript_raw])],
            metadata=metadata,
        )
        for metadata in metadatas
    ]


@pytest.mark.integration
async def test_default_chart(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
):
    # Upload a bit of data
    with open("tests/integration/data/ctf.json", "rb") as f:
        file_content = f.read()
    response = await authed_client.post(
        f"/rest/{test_collection_id}/import_runs_from_file",
        files={"file": ("abc.json", file_content, "application/json")},
    )
    assert response.status_code == 200

    # Create a chart, leave default settings
    response = await authed_client.post(
        f"/rest/chart/{test_collection_id}/create",
        json={},
    )
    assert response.status_code == 200
    data = response.json()
    chart_id = data["id"]
    assert chart_id is not None

    # Backend should choose default settings that show us some sort of data
    response = await authed_client.get(
        f"/rest/chart/{test_collection_id}/{chart_id}/data",
    )
    assert response.status_code == 200
    data = response.json()
    stats = data["result"]["binStats"]

    assert stats != {}


@pytest.mark.integration
async def test_available_metadata_keys(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
):
    metadata_1 = {
        "agent_scaffold": "foo",
        "scores": {"int_float_bool_null": 1},
    }
    metadata_2 = {
        "agent_scaffold": "foo",
        "scores": {"int_float_bool_null": 0.1},
    }
    metadata_3 = {
        "agent_scaffold": "bar",
        "scores": {"int_float_bool_null": False},
    }
    metadata_4 = {
        "agent_scaffold": "bar",
        "scores": {"int_float_bool_null": None},
    }

    agent_runs = runs_with_metadata([metadata_1, metadata_2, metadata_3, metadata_4])

    # Insert agent runs directly via MonoService (bypasses async worker queue)
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    # Create a rubric with a custom output schema
    rubric_payload = {
        "rubric": {
            "rubric_text": "Evaluate the quality of the response",
            "judge_model": {
                "provider": "anthropic",
                "model_name": "claude-3-5-sonnet-20241022",
                "reasoning_effort": "low",
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "quality_score": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 10,
                        "description": "Quality score from 0-10",
                    },
                    "summary": {"type": "string"},  # Not a valid key because not an enum
                    "category": {"type": "string", "enum": ["excellent", "good", "fair", "poor"]},
                    "is_helpful": {"type": "boolean"},
                },
            },
        }
    }

    response = await authed_client.post(
        f"/rest/rubric/{test_collection_id}/rubric",
        json=rubric_payload,
    )
    assert response.status_code == 200

    response = await authed_client.get(
        f"/rest/chart/{test_collection_id}/metadata",
    )
    assert response.status_code == 200
    data = response.json()
    dimension_names = [m["name"] for m in data["dimensions"]]
    measure_names = [m["name"] for m in data["measures"]]

    assert "agent_scaffold" in dimension_names

    assert "scores.int_float_bool_null" in measure_names

    # Integer can be dimension or measure
    assert "quality_score" in measure_names
    assert "quality_score" in dimension_names

    # String enum can only be dimension
    assert "category" in dimension_names
    assert "category" not in measure_names

    # Boolean can be measure or dimension
    assert "is_helpful" in measure_names
    assert "is_helpful" in dimension_names

    # Non-enum string can't be either
    assert "explanation" not in dimension_names
    assert "explanation" not in measure_names


@pytest.mark.integration
async def test_chart_stats_simple(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
):
    metadata_1 = {
        "agent_scaffold": "foo",
        "scores": {"points": 1},
    }
    metadata_2 = {
        "agent_scaffold": "foo",
        "scores": {"points": 2},
    }
    metadata_3 = {
        "agent_scaffold": "bar",
        "scores": {"points": 3},
    }
    metadata_4 = {
        "agent_scaffold": "bar",
        "scores": {"points": 4},
    }

    agent_runs = runs_with_metadata([metadata_1, metadata_2, metadata_3, metadata_4])

    # Insert agent runs directly via MonoService (bypasses async worker queue)
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    # Create a chart, leave default settings
    response = await authed_client.post(
        f"/rest/chart/{test_collection_id}/create",
        json={
            "x_key": "ar.metadata_json->>agent_scaffold",
            "y_key": "ar.metadata_json->scores->>points",
        },
    )
    assert response.status_code == 200

    data = response.json()
    chart_id = data["id"]
    assert chart_id is not None

    response = await authed_client.get(
        f"/rest/chart/{test_collection_id}/{chart_id}/data",
    )
    assert response.status_code == 200
    data = response.json()
    stats = data["result"]["binStats"]

    bin1 = stats["ar.metadata_json->>agent_scaffold,foo"]
    assert bin1["mean"] == 1.5
    assert bin1["n"] == 2

    bin2 = stats["ar.metadata_json->>agent_scaffold,bar"]
    assert bin2["mean"] == 3.5
    assert bin2["n"] == 2


@pytest.mark.integration
async def test_chart_stats_negative_numbers(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    mono_service: MonoService,
    test_user: User,
):
    """Regression test: negative numbers should be included in count and mean calculations."""
    metadata_1 = {
        "agent_scaffold": "foo",
        "scores": {"rating": -5},
    }
    metadata_2 = {
        "agent_scaffold": "foo",
        "scores": {"rating": -3},
    }
    metadata_3 = {
        "agent_scaffold": "foo",
        "scores": {"rating": 2},
    }
    metadata_4 = {
        "agent_scaffold": "bar",
        "scores": {"rating": -10},
    }

    agent_runs = runs_with_metadata([metadata_1, metadata_2, metadata_3, metadata_4])

    # Insert agent runs directly via MonoService (bypasses async worker queue)
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=agent_runs)

    response = await authed_client.post(
        f"/rest/chart/{test_collection_id}/create",
        json={
            "x_key": "ar.metadata_json->>agent_scaffold",
            "y_key": "ar.metadata_json->scores->>rating",
        },
    )
    assert response.status_code == 200

    data = response.json()
    chart_id = data["id"]

    response = await authed_client.get(
        f"/rest/chart/{test_collection_id}/{chart_id}/data",
    )
    assert response.status_code == 200
    data = response.json()
    stats = data["result"]["binStats"]

    bin1 = stats["ar.metadata_json->>agent_scaffold,foo"]
    # Mean of -5, -3, 2 = -6/3 = -2
    assert bin1["mean"] == -2.0
    # All 3 negative and positive values should be counted
    assert bin1["n"] == 3

    bin2 = stats["ar.metadata_json->>agent_scaffold,bar"]
    assert bin2["mean"] == -10.0
    # Negative value should be counted
    assert bin2["n"] == 1
