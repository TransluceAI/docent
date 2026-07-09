from datetime import datetime

import pytest

from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import AssistantMessage, ToolMessage, UserMessage
from docent_core._llm_util.providers import openai as openai_provider
from docent_core.docent.services import hodoscope_pipeline
from docent_core.docent.services.hodoscope import HodoscopeAnalysisConfig
from docent_core.docent.services.hodoscope_pipeline import (
    build_hodoscope_outputs,
    embed_hodoscope_summaries,
    extract_hodoscope_actions,
)

EMBEDDING_ENV_VARS = [
    "DOCENT_EMBEDDING_BASE_URL",
    "DOCENT_EMBEDDING_API_KEY",
    "DOCENT_EMBEDDING_MODEL",
    "DOCENT_EMBEDDING_DIMENSIONS",
    "DOCENT_EMBEDDING_DIM",
    "DOCENT_HODOSCOPE_EMBEDDING_MODEL",
    "DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS",
    "DOCENT_HODOSCOPE_EMBEDDING_DIM",
    "DOCENT_HODOSCOPE_EMBEDDING_BASE_URL",
    "DOCENT_HODOSCOPE_EMBEDDING_API_KEY",
    "DOCENT_LLM_PROVIDER",
    "DOCENT_LLM_BASE_URL",
    "DOCENT_LLM_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_ADMIN_KEY",
]


def _transcript(
    transcript_id: str, messages: list, created_at: datetime | None = None
) -> Transcript:
    return Transcript(id=transcript_id, messages=messages, created_at=created_at)


def _clear_embedding_env(monkeypatch: pytest.MonkeyPatch):
    for env_var in EMBEDDING_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)


@pytest.mark.unit
def test_extract_hodoscope_actions_preserves_transcript_and_block_indices():
    first = _transcript(
        "first",
        [
            UserMessage(content="Investigate failure"),
            AssistantMessage(content="I will inspect the logs."),
            ToolMessage(content="log output", function="shell"),
            AssistantMessage(content="The service timed out."),
        ],
        datetime(2024, 1, 1),
    )
    second = _transcript(
        "second",
        [
            UserMessage(content="Patch it"),
            AssistantMessage(content="I will update the retry policy."),
        ],
        datetime(2024, 1, 2),
    )
    agent_run = AgentRun(
        id="run-1",
        transcripts=[second, first],
        metadata={"metadata": {"model": "deepseek-chat"}},
    )

    actions, group_by = extract_hodoscope_actions([agent_run], group_by=None)

    assert group_by == "metadata.model"
    assert [action.transcript_id for action in actions] == ["first", "first", "second"]
    assert [action.transcript_idx for action in actions] == [0, 0, 1]
    assert [action.action_unit_idx for action in actions] == [0, 1, 0]
    assert [action.first_block_idx for action in actions] == [0, 3, 0]
    assert {action.group for action in actions} == {"deepseek-chat"}
    assert "T0B1" in actions[0].action_text
    assert "T0B3" in actions[1].action_text
    assert "T1B1" in actions[2].action_text


@pytest.mark.unit
def test_extract_hodoscope_actions_uses_unknown_group_when_missing():
    agent_run = AgentRun(
        id="run-unknown",
        transcripts=[
            _transcript(
                "transcript",
                [
                    UserMessage(content="Start"),
                    AssistantMessage(content="I will answer."),
                ],
            )
        ],
        metadata={"task": "no model metadata"},
    )

    actions, group_by = extract_hodoscope_actions([agent_run], group_by=None)

    assert group_by == "unknown"
    assert len(actions) == 1
    assert actions[0].group == "unknown"


@pytest.mark.unit
def test_extract_hodoscope_actions_resolves_flat_metadata_field_names():
    agent_run = AgentRun(
        id="run-flat",
        transcripts=[
            _transcript(
                "transcript",
                [
                    UserMessage(content="Start"),
                    AssistantMessage(content="I will answer."),
                ],
            )
        ],
        metadata={"metadata.model": "flat-model"},
    )

    actions, group_by = extract_hodoscope_actions([agent_run], group_by="metadata.model")

    assert group_by == "metadata.model"
    assert len(actions) == 1
    assert actions[0].group == "flat-model"


@pytest.mark.unit
def test_build_hodoscope_outputs_encodes_artifact_and_projection_points(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)
    summaries = [
        {
            "point_id": "run-a:t-a:0:0",
            "trajectory_id": "run-a",
            "turn_id": 0,
            "agent_run_id": "run-a",
            "transcript_id": "t-a",
            "transcript_idx": 0,
            "action_unit_idx": 0,
            "first_block_idx": 1,
            "summary": "Inspect logs\nFor diagnosing the timeout.",
            "action_text": "assistant looked at logs",
            "task_context": "debug timeout",
            "metadata": {"model": "a"},
            "group": "a",
            "embedding": [0.0, 1.0, 0.0],
        },
        {
            "point_id": "run-b:t-b:0:0",
            "trajectory_id": "run-b",
            "turn_id": 0,
            "agent_run_id": "run-b",
            "transcript_id": "t-b",
            "transcript_idx": 0,
            "action_unit_idx": 0,
            "first_block_idx": 1,
            "summary": "Patch retry policy\nFor making calls recover.",
            "action_text": "assistant patched retries",
            "task_context": "fix timeout",
            "metadata": {"model": "b"},
            "group": "b",
            "embedding": [1.0, 0.0, 0.0],
        },
    ]

    artifact, projection = build_hodoscope_outputs(
        summaries,
        HodoscopeAnalysisConfig(projection_method="tsne"),
        group_by="model",
        source="docent:test",
    )

    assert artifact["source"] == "docent:test"
    assert artifact["embedding_model"] == "text-embedding-3-small"
    assert len(artifact["summaries"]) == 2
    assert all(summary["embedding"] for summary in artifact["summaries"])

    assert projection["requested_projection_method"] == "tsne"
    assert projection["projection_method"] == "pca"
    assert projection["group_by"] == "model"
    assert projection["groups"] == [{"name": "a", "count": 1}, {"name": "b", "count": 1}]
    assert len(projection["points"]) == 2
    assert projection["points"][0]["agent_run_id"] == "run-a"
    assert projection["points"][0]["first_block_idx"] == 1
    assert projection["points"][0]["embedding"]
    assert isinstance(projection["points"][0]["x"], float)
    assert isinstance(projection["points"][0]["fps_rank"], int)


@pytest.mark.unit
def test_build_hodoscope_outputs_handles_empty_inputs():
    artifact, projection = build_hodoscope_outputs(
        [],
        HodoscopeAnalysisConfig(),
        group_by="unknown",
        source="docent:empty",
    )

    assert artifact["summaries"] == []
    assert projection["points"] == []
    assert projection["groups"] == []


@pytest.mark.unit
def test_hodoscope_embedding_config_uses_local_embedding_env(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("DOCENT_EMBEDDING_MODEL", "local-bge-m3")
    monkeypatch.setenv("DOCENT_EMBEDDING_DIMENSIONS", "auto")

    config = HodoscopeAnalysisConfig()

    assert config.embedding_model == "local-bge-m3"
    assert config.embedding_dimensionality is None


@pytest.mark.unit
def test_hodoscope_embedding_config_allows_hodoscope_specific_override(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("DOCENT_EMBEDDING_MODEL", "global-embedding-model")
    monkeypatch.setenv("DOCENT_EMBEDDING_DIMENSIONS", "512")
    monkeypatch.setenv("DOCENT_HODOSCOPE_EMBEDDING_MODEL", "hodoscope-embedding-model")
    monkeypatch.setenv("DOCENT_HODOSCOPE_EMBEDDING_DIMENSIONS", "384")

    config = HodoscopeAnalysisConfig()

    assert config.embedding_model == "hodoscope-embedding-model"
    assert config.embedding_dimensionality == 384


@pytest.mark.unit
def test_openai_compatible_embedding_client_reuses_custom_llm_config(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("DOCENT_LLM_PROVIDER", "custom")
    monkeypatch.setenv("DOCENT_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("DOCENT_LLM_API_KEY", "test-key")

    client = openai_provider.get_openai_compatible_embedding_client_async()

    assert openai_provider.get_openai_compatible_embedding_config_error() is None
    assert str(client.base_url).rstrip("/") == "http://localhost:8000/v1"
    assert client.api_key == "test-key"


@pytest.mark.unit
def test_openai_compatible_embedding_client_accepts_call_overrides(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)

    client = openai_provider.get_openai_compatible_embedding_client_async(
        api_key="override-key",
        base_url="http://localhost:8001/v1",
    )

    assert openai_provider.get_openai_compatible_embedding_config_error(
        api_key="override-key",
        base_url="http://localhost:8001/v1",
    ) is None
    assert str(client.base_url).rstrip("/") == "http://localhost:8001/v1"
    assert client.api_key == "override-key"


@pytest.mark.unit
def test_openai_compatible_embedding_config_reports_missing_key(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)

    error = openai_provider.get_openai_compatible_embedding_config_error()

    assert error is not None
    assert "DOCENT_EMBEDDING_API_KEY" in error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chunked_embedding_helper_sends_text_chunks_to_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)
    seen_batches = []

    async def fake_one_batch(client, batch, model_name, dimensions):
        seen_batches.append(batch)
        return [[0.1, 0.2, 0.3] for _ in batch]

    monkeypatch.setattr(
        openai_provider,
        "get_openai_compatible_embedding_client_async",
        lambda api_key=None, base_url=None: {
            "api_key": api_key,
            "base_url": base_url,
        },
    )
    monkeypatch.setattr(
        openai_provider,
        "_get_openai_embeddings_async_one_batch",
        fake_one_batch,
    )

    embeddings, chunk_to_doc = await openai_provider.get_chunked_openai_embeddings_async(
        ["hello local embedding server"],
        model_name="local-embedding-model",
        dimensions=None,
    )

    assert embeddings == [[0.1, 0.2, 0.3]]
    assert chunk_to_doc == [0]
    assert seen_batches
    assert all(isinstance(item, str) for batch in seen_batches for item in batch)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_hodoscope_summaries_passes_configured_model_and_dimensions(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)
    calls = {}

    async def fake_embeddings(
        texts,
        model_name,
        dimensions,
        max_concurrency,
        callback,
        api_key=None,
        base_url=None,
    ):
        calls["texts"] = texts
        calls["model_name"] = model_name
        calls["dimensions"] = dimensions
        calls["max_concurrency"] = max_concurrency
        calls["api_key"] = api_key
        calls["base_url"] = base_url
        if callback is not None:
            await callback(100)
        return [[0.4, 0.5, 0.6]], [0]

    progress = []

    async def progress_callback(value: int):
        progress.append(value)

    monkeypatch.setattr(
        hodoscope_pipeline,
        "get_openai_compatible_embedding_config_error",
        lambda api_key=None, base_url=None: None,
    )
    monkeypatch.setattr(
        hodoscope_pipeline,
        "get_chunked_openai_embeddings_async",
        fake_embeddings,
    )

    embedded = await embed_hodoscope_summaries(
        [
            {
                "point_id": "run:t:0:0",
                "summary": "Action: inspected logs\nFor: diagnosing a failure",
            }
        ],
        progress_callback=progress_callback,
        model_name="local-embedding-model",
        dimensions=None,
    )

    assert calls == {
        "texts": ["Action: inspected logs\nFor: diagnosing a failure"],
        "model_name": "local-embedding-model",
        "dimensions": None,
        "max_concurrency": 25,
        "api_key": None,
        "base_url": None,
    }
    assert progress == [100]
    assert embedded[0]["embedding"] == [0.4, 0.5, 0.6]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_hodoscope_summaries_uses_hodoscope_endpoint_overrides(
    monkeypatch: pytest.MonkeyPatch,
):
    _clear_embedding_env(monkeypatch)
    monkeypatch.setenv("DOCENT_HODOSCOPE_EMBEDDING_BASE_URL", "http://localhost:8002/v1")
    monkeypatch.setenv("DOCENT_HODOSCOPE_EMBEDDING_API_KEY", "hodo-key")
    calls = {}

    async def fake_embeddings(
        texts,
        model_name,
        dimensions,
        max_concurrency,
        callback,
        api_key=None,
        base_url=None,
    ):
        calls["api_key"] = api_key
        calls["base_url"] = base_url
        return [[0.7, 0.8, 0.9]], [0]

    monkeypatch.setattr(
        hodoscope_pipeline,
        "get_openai_compatible_embedding_config_error",
        lambda api_key=None, base_url=None: None,
    )
    monkeypatch.setattr(
        hodoscope_pipeline,
        "get_chunked_openai_embeddings_async",
        fake_embeddings,
    )

    embedded = await embed_hodoscope_summaries(
        [{"point_id": "run:t:0:0", "summary": "Action: listed files"}],
        model_name="hodoscope-model",
        dimensions=1024,
    )

    assert calls == {
        "api_key": "hodo-key",
        "base_url": "http://localhost:8002/v1",
    }
    assert embedded[0]["embedding"] == [0.7, 0.8, 0.9]
