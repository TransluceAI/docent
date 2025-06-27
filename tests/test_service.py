import random
from typing import Any, Generator, Set

import pytest
import pytest_asyncio

from docent_core._db_service.service import DBService
from docent_core._env_util import ENV
from docent_core._frames.filters import FrameDimension, PrimitiveFilter
from docent_core._frames.transcript import Transcript, TranscriptMetadata
from docent_core._frames.types import Datapoint


def _generate_dummy_datapoints(
    num_tasks: int, num_samples_per_task: int, num_epochs_per_sample: int
) -> Generator[Datapoint, None, None]:
    """Construct a minimal `Datapoint` object that is fully serialisable by `SQLADatapoint`.

    We intentionally keep the transcript empty (``messages=[]``) because the DB code paths that
    these tests exercise never look at the actual message content – they only need the field to
    be JSON-serialisable.
    """

    for task_idx in range(num_tasks):
        for sample_idx in range(num_samples_per_task):
            for epoch_idx in range(num_epochs_per_sample):
                metadata = TranscriptMetadata(
                    task_id=f"pytest_task_{task_idx}",
                    sample_id=f"pytest_task_{task_idx}_sample_{sample_idx}",
                    original_sample_id_type="str",
                    epoch_id=epoch_idx,
                    experiment_id="pytest_exp_default",
                    intervention_description=None,
                    intervention_index=None,
                    intervention_timestamp=None,
                    model="pytest_model",
                    task_args={},
                    is_loading_messages=False,
                    scores={"score": random.random()},
                    default_score_key=None,
                    scoring_metadata=None,
                    additional_metadata=None,
                )

                transcript = Transcript(
                    messages=[
                        {
                            "role": "user",
                            "content": "Hello, world!",
                        }
                    ],
                    metadata=metadata,
                )
                yield Datapoint.from_transcript(transcript)


@pytest_asyncio.fixture(scope="session")
async def db_service_session_scoped():
    """
    Session-scoped fixture to initialize DBService.
    Creates tables once per session and drops them after all tests.
    """
    # Ensure that the test database name implies it's for testing.
    if (test_db_name := ENV.get("DOCENT_PG_DATABASE")) is None:
        raise ValueError("DOCENT_PG_DATABASE is not set")
    if not test_db_name.startswith("_pytest"):
        raise ValueError("DOCENT_PG_DATABASE is not a test database (starts with '_pytest')")

    service = await DBService.init()
    yield service


@pytest_asyncio.fixture
async def db_service(db_service_session_scoped: DBService):
    """
    Test-scoped fixture that provides the DBService instance.
    It can also be used to clean up specific data between tests if needed,
    though full table drops are handled by the session-scoped fixture.
    """
    yield db_service_session_scoped


@pytest.mark.asyncio
async def test_add_datapoints(db_service: DBService):
    """
    Tests adding datapoints to a FrameGrid, ensuring data integrity
    and proper re-clustering of MECE metadata dimensions.
    """
    # Create a new FG
    fg_id = await db_service.create(name="pytest_fg", description="this is a test framegrid")

    # Create datapoints.
    datapoints: list[Datapoint] = list(
        _generate_dummy_datapoints(num_tasks=2, num_samples_per_task=10, num_epochs_per_sample=1)
    )
    datapoint_ids = {dp.id for dp in datapoints}

    # Define and upsert a MECE metadata dimension before adding datapoints.
    METADATA_KEY = "sample_id"
    mece_dim = FrameDimension(
        name="sample id mece dimension",
        metadata_key=METADATA_KEY,
        maintain_mece=True,
    )
    await db_service.upsert_dim(fg_id, mece_dim)

    # Add datapoints to the FG, which should trigger re-clustering of the MECE dim
    await db_service.add_datapoints(fg_id, datapoints)

    # 1. Check that all datapoints are in the FG
    retrieved_datapoints = await db_service.get_all_data(fg_id)
    retrieved_datapoint_ids = {dp.id for dp in retrieved_datapoints}
    assert retrieved_datapoint_ids == datapoint_ids, "Not all added datapoints were retrieved"

    # 2. Check that the MECE metadata dimension has been re-clustered properly

    # Get unique expected metadata values for the key from the source datapoints
    expected_metadata_values: Set[Any] = set()
    # Pre-bin datapoints by their metadata value for efficient lookup later
    expected_datapoints_by_value: dict[Any, Set[str]] = {}
    for dp in datapoints:
        if hasattr(dp.metadata, METADATA_KEY):
            value = getattr(dp.metadata, METADATA_KEY)
            expected_metadata_values.add(value)
            expected_datapoints_by_value.setdefault(value, set()).add(dp.id)

    retrieved_dim_filters = await db_service.get_dim_filters(fg_id, mece_dim.id)

    assert len(retrieved_dim_filters) == len(expected_metadata_values), (
        f"Expected {len(expected_metadata_values)} filters for MECE dim, "
        f"got {len(retrieved_dim_filters)}"
    )

    # Loop through and ensure each filter matches the correct datapoints
    processed_filter_values: Set[Any] = set()
    for db_filter in retrieved_dim_filters:
        assert isinstance(
            db_filter, PrimitiveFilter
        ), f"Filter {db_filter.id} is not a PrimitiveFilter"
        assert db_filter.key_path == (
            "metadata",
            METADATA_KEY,
        ), f"Filter {db_filter.id} has incorrect key_path"

        # Add value to running list
        filter_value = db_filter.value
        processed_filter_values.add(filter_value)

        # Check judgments for this filter
        judgments = await db_service.get_matching_judgments(fg_id, db_filter.id)
        judged_datapoint_ids = {j.datapoint_id for j in judgments}

        # Efficiently get the expected datapoints for the current filter value
        current_expected_datapoint_ids = expected_datapoints_by_value.get(filter_value, set())

        assert judged_datapoint_ids == current_expected_datapoint_ids, (
            f"Judgments for filter value '{filter_value}' ({len(judged_datapoint_ids)}) "
            f"do not match expected datapoints ({len(current_expected_datapoint_ids)})"
        )

    assert (
        processed_filter_values == expected_metadata_values
    ), "The set of filter values does not match the set of unique metadata values"

    # TODO(mengk): clean up: await db_service.delete_framegrid(fg_id)
    # This depends on whether tests are isolated or share a DB instance.
    # If isolated (e.g., via fixtures creating/destroying DB for each test),
    # explicit cleanup here might not be necessary.
