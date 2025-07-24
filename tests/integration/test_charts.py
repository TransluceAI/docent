from typing import Any

import httpx
import pytest
from pydantic import Field

from docent.data_models import AgentRun, BaseAgentRunMetadata, Transcript
from docent.data_models.chat import parse_chat_message


class MyMetadata(BaseAgentRunMetadata):
    agent_scaffold: str = Field(description="Agent scaffold in which the agent was run")


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
            transcripts={
                "default": Transcript(messages=[parse_chat_message(msg) for msg in transcript_raw])
            },
            metadata=MyMetadata(**metadata),
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
        f"/rest/{test_collection_id}/agent_runs",
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

    # Upload agent runs data directly via API
    payload = {"agent_runs": [ar.model_dump(mode="json") for ar in agent_runs]}
    response = await authed_client.post(
        f"/rest/{test_collection_id}/agent_runs",
        json=payload,
    )
    assert response.status_code == 200

    response = await authed_client.get(
        f"/rest/chart/{test_collection_id}/metadata",
    )
    assert response.status_code == 200
    data = response.json()
    dimensions = data["fields"]["dimensions"]
    measures = data["fields"]["measures"]

    assert any("agent_scaffold" in m["name"] for m in dimensions)

    assert any("int_float_bool_null" in m["name"] for m in measures)


@pytest.mark.integration
async def test_chart_stats_simple(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
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

    payload = {"agent_runs": [ar.model_dump(mode="json") for ar in agent_runs]}
    response = await authed_client.post(
        f"/rest/{test_collection_id}/agent_runs",
        json=payload,
    )
    assert response.status_code == 200

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
