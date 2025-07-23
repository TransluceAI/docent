"""Unit tests for isolated business logic in DiffService."""

from typing import Any, Dict
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from docent.data_models.agent_run import AgentRun
from docent.data_models.metadata import BaseAgentRunMetadata, BaseMetadata
from docent.data_models.transcript import Transcript
from docent_core.services.diff import DiffService


def create_agent_run(metadata: Dict[str, Any] | None = None) -> AgentRun:
    """Factory for creating test AgentRun objects."""
    if metadata and "scores" not in metadata:
        metadata["scores"] = {}

    agent_metadata = (
        BaseAgentRunMetadata(**metadata) if metadata else BaseAgentRunMetadata(scores={})
    )
    transcript = Transcript(messages=[], metadata=BaseMetadata())

    return AgentRun(id=str(uuid4()), metadata=agent_metadata, transcripts={"default": transcript})


@pytest.fixture
def diff_service():
    return DiffService(session=MagicMock(), session_cm_factory=MagicMock(), service=MagicMock())


def _call_pair_runs(
    diff_service: DiffService,
    agent_runs: list[AgentRun],
    grouping_md_fields: list[str] | None = None,
    md_field_value_1: tuple[str, Any] = ("model", "gpt-4"),
    md_field_value_2: tuple[str, Any] = ("model", "claude"),
    sample_if_multiple: bool = True,
    errors_ok: bool = True,
) -> list[tuple[AgentRun, AgentRun]]:
    """Helper to call pair_runs with sensible defaults."""
    return diff_service.pair_runs(
        agent_runs=agent_runs,
        grouping_md_fields=grouping_md_fields if grouping_md_fields is not None else ["task"],
        md_field_value_1=md_field_value_1,
        md_field_value_2=md_field_value_2,
        sample_if_multiple=sample_if_multiple,
        errors_ok=errors_ok,
    )


def test_basic_pairing_validation(diff_service: DiffService):
    agent_runs = [
        create_agent_run({"task": "A", "model": "gpt-4"}),
        create_agent_run({"task": "A", "model": "claude"}),
        create_agent_run({"task": "B", "model": "gpt-4"}),
        create_agent_run({"task": "B", "model": "claude"}),
    ]

    paired_runs = _call_pair_runs(diff_service, agent_runs)

    assert len(paired_runs) == 2
    for run1, run2 in paired_runs:
        models = {run1.metadata.model, run2.metadata.model}  # type: ignore
        assert models == {"gpt-4", "claude"}
        assert run1.metadata.task == run2.metadata.task  # type: ignore


def test_error_handling_when_errors_not_ok(diff_service: DiffService):
    agent_runs = [create_agent_run({"task": "A", "model": "gpt-4"})]

    with pytest.raises(ValueError, match="Pairing failed"):
        _call_pair_runs(diff_service, agent_runs, errors_ok=False)


def test_sampling_multiple_runs(diff_service: DiffService):
    agent_runs = [
        create_agent_run({"task": "A", "model": "gpt-4"}),
        create_agent_run({"task": "A", "model": "gpt-4"}),  # duplicate
        create_agent_run({"task": "A", "model": "claude"}),
    ]

    paired_runs = _call_pair_runs(diff_service, agent_runs, sample_if_multiple=True)

    assert len(paired_runs) == 1


def test_complex_grouping_fields(diff_service: DiffService):
    agent_runs = [
        create_agent_run({"task": "A", "difficulty": "easy", "model": "gpt-4"}),
        create_agent_run({"task": "A", "difficulty": "easy", "model": "claude"}),
        create_agent_run({"task": "A", "difficulty": "hard", "model": "gpt-4"}),
        create_agent_run({"task": "B", "difficulty": "easy", "model": "gpt-4"}),
    ]

    paired_runs = _call_pair_runs(
        diff_service, agent_runs, grouping_md_fields=["task", "difficulty"]
    )

    assert len(paired_runs) == 1
    run1, run2 = paired_runs[0]
    assert run1.metadata.task == "A" and run1.metadata.difficulty == "easy"  # type: ignore
    assert run2.metadata.task == "A" and run2.metadata.difficulty == "easy"  # type: ignore


@pytest.mark.parametrize(
    "agent_runs_data,expected_pairs",
    [
        ([], 0),  # empty input
        ([{"task": "A", "model": "gpt-4"}], 0),  # single run
        (
            [{"task": "A", "model": "gpt-4"}, {"task": "A", "model": "claude"}],
            1,
        ),  # perfect pair
        (
            [{"task": "A", "model": "gpt-4"}, {"task": "A"}, {"model": "claude"}],
            0,
        ),  # missing fields
        (
            [{"task": "A", "model": "gpt-4"}, {"task": "B", "model": "claude"}],
            0,
        ),  # mismatched tasks
    ],
)
def test_pairing_scenarios(
    diff_service: DiffService, agent_runs_data: list[Dict[str, Any]], expected_pairs: int
):
    agent_runs = [create_agent_run(data) for data in agent_runs_data]
    paired_runs = _call_pair_runs(diff_service, agent_runs)
    assert len(paired_runs) == expected_pairs
