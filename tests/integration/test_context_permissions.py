"""Integration tests for context permission checking."""

from typing import TYPE_CHECKING, AsyncContextManager, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, UserMessage
from docent.data_models.transcript import Transcript
from docent.sdk.llm_context import AgentRunRef, LLMContextSpec, Prompt
from docent.sdk.llm_request import ExternalAnalysisResult, LLMRequest
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.result_set import DEFAULT_OUTPUT_SCHEMA, ResultSetService

if TYPE_CHECKING:
    import httpx

    from docent_core.docent.services.result_set import ResultSetService


@pytest_asyncio.fixture
async def second_user(mono_service: MonoService) -> User:
    """Create a second user with no collection access."""
    return await mono_service.create_user(email="second_user@example.com", password="password")


@pytest_asyncio.fixture
async def second_collection_id(mono_service: MonoService, second_user: User) -> str:
    """Create a collection owned by second_user."""
    return await mono_service.create_collection(
        name="second_collection",
        description="Collection for permission tests",
        user=second_user,
    )


@pytest_asyncio.fixture
async def agent_run_in_collection(
    mono_service: MonoService, test_collection_id: str, test_user: User
) -> AgentRun:
    """Create an agent run in the test collection."""
    transcript = Transcript(
        messages=[
            UserMessage(content="Hello"),
            AssistantMessage(content="Hi there"),
        ],
        metadata={"key": "value"},
    )
    agent_run = AgentRun(
        transcripts=[transcript],
        metadata={"task": "test"},
    )
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=[agent_run])
    return agent_run


@pytest_asyncio.fixture
async def agent_run_in_second_collection(
    mono_service: MonoService, second_collection_id: str, second_user: User
) -> AgentRun:
    """Create an agent run in the second collection."""
    transcript = Transcript(
        messages=[
            UserMessage(content="Secret message"),
            AssistantMessage(content="Secret response"),
        ],
        metadata={"secret": "data"},
    )
    agent_run = AgentRun(
        transcripts=[transcript],
        metadata={"task": "secret"},
    )
    ctx = await mono_service.get_default_view_ctx(second_collection_id, second_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=[agent_run])
    return agent_run


# =============================================================================
# Tests for get_readable_collection_ids
# =============================================================================


@pytest.mark.integration
async def test_get_readable_collection_ids_own_collection(
    mono_service: MonoService, test_collection_id: str, test_user: User
) -> None:
    """User can read collections they have access to."""
    readable = await mono_service.get_readable_collection_ids(test_user, {test_collection_id})
    assert test_collection_id in readable


@pytest.mark.integration
async def test_get_readable_collection_ids_no_access(
    mono_service: MonoService,
    second_collection_id: str,
    test_user: User,
) -> None:
    """User cannot read collections they lack access to."""
    readable = await mono_service.get_readable_collection_ids(test_user, {second_collection_id})
    assert second_collection_id not in readable


@pytest.mark.integration
async def test_get_readable_collection_ids_empty_input(
    mono_service: MonoService, test_user: User
) -> None:
    """Empty input returns empty set."""
    readable = await mono_service.get_readable_collection_ids(test_user, set())
    assert readable == set()


@pytest.mark.integration
async def test_get_readable_collection_ids_mixed_access(
    mono_service: MonoService,
    test_collection_id: str,
    second_collection_id: str,
    test_user: User,
) -> None:
    """User can read some collections but not others."""
    readable = await mono_service.get_readable_collection_ids(
        test_user, {test_collection_id, second_collection_id}
    )
    assert test_collection_id in readable
    assert second_collection_id not in readable


# =============================================================================
# Tests for verify_context_access
# =============================================================================


@pytest.mark.integration
async def test_verify_context_access_own_collection(
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
    agent_run_in_collection: AgentRun,
) -> None:
    """Succeeds when user has READ on all referenced collections."""
    spec = LLMContextSpec()
    spec.add_agent_run(id=agent_run_in_collection.id, collection_id=test_collection_id)

    # Should not raise
    await mono_service.verify_context_access(test_user, spec)


@pytest.mark.integration
async def test_verify_context_access_no_permission(
    mono_service: MonoService,
    second_collection_id: str,
    test_user: User,
    agent_run_in_second_collection: AgentRun,
) -> None:
    """Fails when user lacks READ on a referenced collection."""
    spec = LLMContextSpec()
    spec.add_agent_run(id=agent_run_in_second_collection.id, collection_id=second_collection_id)

    with pytest.raises(PermissionError, match="lacks READ permission"):
        await mono_service.verify_context_access(test_user, spec)


@pytest.mark.integration
async def test_verify_context_access_item_not_found(
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
) -> None:
    """Fails when item doesn't exist."""
    spec = LLMContextSpec()
    spec.add_agent_run(id="nonexistent-uuid-12345", collection_id=test_collection_id)

    with pytest.raises(PermissionError, match="not found"):
        await mono_service.verify_context_access(test_user, spec)


@pytest.mark.integration
async def test_verify_context_access_spoofed_collection(
    mono_service: MonoService,
    test_collection_id: str,
    second_collection_id: str,
    test_user: User,
    agent_run_in_second_collection: AgentRun,
) -> None:
    """Fails when item doesn't belong to claimed collection (ownership spoofing)."""
    spec = LLMContextSpec()
    # Item is in second_collection, but we claim it's in test_collection
    spec.add_agent_run(id=agent_run_in_second_collection.id, collection_id=test_collection_id)

    with pytest.raises(PermissionError, match="does not belong to claimed collection"):
        await mono_service.verify_context_access(test_user, spec)


@pytest.mark.integration
async def test_submit_results_direct_rejects_cross_collection_spoof(
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
    db_session: AsyncSession,
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
) -> None:
    """submit_results_direct should reject results that reference runs from another collection."""
    # Setup: create another collection with its own run
    other_user = await mono_service.create_user(email="other@example.com", password="password")
    other_collection_id = await mono_service.create_collection(
        name="other", description="other collection", user=other_user
    )

    other_run = AgentRun(
        transcripts=[
            Transcript(
                messages=[UserMessage(content="secret"), AssistantMessage(content="response")]
            )
        ],
        metadata={"owner": "other"},
    )
    other_ctx = await mono_service.get_default_view_ctx(other_collection_id, other_user)
    await mono_service.add_agent_runs(ctx=other_ctx, agent_runs=[other_run])

    # Create a result set in the main test collection
    result_set_svc = ResultSetService(db_session, session_cm_factory)
    result_set = await result_set_svc.create_result_set(
        collection_id=test_collection_id,
        user_id=test_user.id,
        output_schema=DEFAULT_OUTPUT_SCHEMA,
        name="spoof-test",
    )
    await db_session.commit()

    # Craft a result that references the other collection's run but spoofs collection_id
    spoofed_prompt = Prompt([AgentRunRef(id=other_run.id, collection_id=test_collection_id)])
    external_result = ExternalAnalysisResult(
        request=LLMRequest(prompt=spoofed_prompt),
        output={"output": "hello"},
    )

    with pytest.raises(ValueError, match="belongs to collection"):
        await result_set_svc.submit_results_direct(
            result_set.id,
            [external_result],
            expected_collection_id=test_collection_id,
        )


@pytest.mark.integration
async def test_verify_context_access_empty_spec(mono_service: MonoService, test_user: User) -> None:
    """Succeeds with empty spec."""
    spec = LLMContextSpec()

    # Should not raise
    await mono_service.verify_context_access(test_user, spec)


@pytest.mark.integration
async def test_verify_context_access_transcript_ref(
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
    agent_run_in_collection: AgentRun,
) -> None:
    """Succeeds with transcript reference from own collection."""
    transcript = agent_run_in_collection.transcripts[0]
    spec = LLMContextSpec()
    spec.add_transcript(
        id=transcript.id,
        agent_run_id=agent_run_in_collection.id,
        collection_id=test_collection_id,
    )

    # Should not raise
    await mono_service.verify_context_access(test_user, spec)


@pytest.mark.integration
async def test_verify_context_access_transcript_no_permission(
    mono_service: MonoService,
    second_collection_id: str,
    test_user: User,
    agent_run_in_second_collection: AgentRun,
) -> None:
    """Fails when user lacks READ on transcript's collection."""
    transcript = agent_run_in_second_collection.transcripts[0]
    spec = LLMContextSpec()
    spec.add_transcript(
        id=transcript.id,
        agent_run_id=agent_run_in_second_collection.id,
        collection_id=second_collection_id,
    )

    with pytest.raises(PermissionError, match="lacks READ permission"):
        await mono_service.verify_context_access(test_user, spec)


# =============================================================================
# Tests for chat endpoints
# =============================================================================


@pytest.mark.integration
async def test_chat_start_with_valid_context(
    authed_client: "httpx.AsyncClient",
    test_collection_id: str,
    agent_run_in_collection: AgentRun,
) -> None:
    """POST /chat/start succeeds with valid context user can access."""
    spec = LLMContextSpec()
    spec.add_agent_run(id=agent_run_in_collection.id, collection_id=test_collection_id)

    response = await authed_client.post(
        "/rest/chat/start",
        json={"context_serialized": spec.model_dump(mode="json")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data


@pytest.mark.integration
async def test_chat_start_no_permission(
    authed_client: "httpx.AsyncClient",
    second_collection_id: str,
    agent_run_in_second_collection: AgentRun,
) -> None:
    """POST /chat/start returns 403 when user lacks access to referenced collection."""
    spec = LLMContextSpec()
    spec.add_agent_run(id=agent_run_in_second_collection.id, collection_id=second_collection_id)

    response = await authed_client.post(
        "/rest/chat/start",
        json={"context_serialized": spec.model_dump(mode="json")},
    )
    assert response.status_code == 403
    assert "lacks READ permission" in response.json()["detail"]


@pytest.mark.integration
async def test_chat_start_spoofed_collection(
    authed_client: "httpx.AsyncClient",
    test_collection_id: str,
    agent_run_in_second_collection: AgentRun,
) -> None:
    """POST /chat/start returns 403 when item doesn't belong to claimed collection."""
    spec = LLMContextSpec()
    # Item is in second_collection, but we claim it's in test_collection
    spec.add_agent_run(id=agent_run_in_second_collection.id, collection_id=test_collection_id)

    response = await authed_client.post(
        "/rest/chat/start",
        json={"context_serialized": spec.model_dump(mode="json")},
    )
    assert response.status_code == 403
    assert "does not belong to claimed collection" in response.json()["detail"]


@pytest.mark.integration
async def test_add_context_item_with_permission(
    authed_client: "httpx.AsyncClient",
    test_collection_id: str,
    agent_run_in_collection: AgentRun,
) -> None:
    """POST /conversation/{session_id}/context succeeds when user has READ."""
    # First create a session
    spec = LLMContextSpec()
    spec.add_agent_run(id=agent_run_in_collection.id, collection_id=test_collection_id)

    create_response = await authed_client.post(
        "/rest/chat/start",
        json={"context_serialized": spec.model_dump(mode="json")},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    # Create another agent run to add
    transcript = agent_run_in_collection.transcripts[0]

    # Add the transcript to the context
    add_response = await authed_client.post(
        f"/rest/chat/conversation/{session_id}/context",
        json={"item_id": transcript.id},
    )
    assert add_response.status_code == 200


@pytest.mark.integration
async def test_add_context_item_no_permission(
    authed_client: "httpx.AsyncClient",
    test_collection_id: str,
    agent_run_in_collection: AgentRun,
    agent_run_in_second_collection: AgentRun,
) -> None:
    """POST /conversation/{session_id}/context returns 403 when user lacks READ."""
    # First create a session with an item the user can access
    spec = LLMContextSpec()
    spec.add_agent_run(id=agent_run_in_collection.id, collection_id=test_collection_id)

    create_response = await authed_client.post(
        "/rest/chat/start",
        json={"context_serialized": spec.model_dump(mode="json")},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    # Try to add an item from a collection the user can't access
    add_response = await authed_client.post(
        f"/rest/chat/conversation/{session_id}/context",
        json={"item_id": agent_run_in_second_collection.id},
    )
    assert add_response.status_code == 403
    assert "read permission" in add_response.json()["detail"].lower()


# =============================================================================
# Tests for ResultSetService.submit_requests
# =============================================================================


@pytest_asyncio.fixture
async def result_set_service(
    db_session: "AsyncSession",
    session_cm_factory: "Callable[[], AsyncContextManager[AsyncSession]]",
) -> "ResultSetService":
    """Create a ResultSetService for testing."""
    from docent_core.docent.services.result_set import ResultSetService

    return ResultSetService(db_session, session_cm_factory)


@pytest_asyncio.fixture
async def test_result_set_id(
    result_set_service: "ResultSetService",
    test_collection_id: str,
    test_user: User,
) -> str:
    """Create a result set in the test collection."""
    result_set = await result_set_service.create_result_set(
        collection_id=test_collection_id,
        user_id=test_user.id,
        output_schema={"type": "object", "properties": {"output": {"type": "string"}}},
        name="test_result_set",
    )
    return result_set.id


@pytest.mark.integration
async def test_submit_requests_valid_items(
    result_set_service: "ResultSetService",
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
    agent_run_in_collection: AgentRun,
    test_result_set_id: str,
) -> None:
    """submit_requests succeeds when all items belong to the result set's collection."""
    from docent.sdk.llm_context import Prompt
    from docent.sdk.llm_request import LLMRequest

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)

    prompt = Prompt(
        [
            AgentRunRef(id=agent_run_in_collection.id, collection_id=test_collection_id),
            "Analyze this agent run.",
        ]
    )
    request = LLMRequest(prompt=prompt)

    # Should not raise
    job_id = await result_set_service.submit_requests(
        ctx=ctx,
        result_set_id=test_result_set_id,
        requests=[request],
    )
    assert job_id is not None


@pytest.mark.integration
async def test_submit_requests_item_not_found(
    result_set_service: "ResultSetService",
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
    test_result_set_id: str,
) -> None:
    """submit_requests fails when an item doesn't exist."""
    from docent.sdk.llm_context import Prompt
    from docent.sdk.llm_request import LLMRequest

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)

    prompt = Prompt(
        [
            AgentRunRef(id="nonexistent-uuid-12345", collection_id=test_collection_id),
            "Analyze this agent run.",
        ]
    )
    request = LLMRequest(prompt=prompt)

    with pytest.raises(ValueError, match="not found"):
        await result_set_service.submit_requests(
            ctx=ctx,
            result_set_id=test_result_set_id,
            requests=[request],
        )


@pytest.mark.integration
async def test_submit_requests_wrong_collection(
    result_set_service: "ResultSetService",
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
    agent_run_in_second_collection: AgentRun,
    test_result_set_id: str,
) -> None:
    """submit_requests fails when an item belongs to a different collection."""
    from docent.sdk.llm_context import Prompt
    from docent.sdk.llm_request import LLMRequest

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)

    # Item is in second_collection, but we claim it's in test_collection
    prompt = Prompt(
        [
            AgentRunRef(id=agent_run_in_second_collection.id, collection_id=test_collection_id),
            "Analyze this agent run.",
        ]
    )
    request = LLMRequest(prompt=prompt)

    with pytest.raises(ValueError, match="belongs to collection"):
        await result_set_service.submit_requests(
            ctx=ctx,
            result_set_id=test_result_set_id,
            requests=[request],
        )


@pytest.mark.integration
async def test_submit_requests_bulk_with_one_bad_item(
    result_set_service: "ResultSetService",
    mono_service: MonoService,
    test_collection_id: str,
    test_user: User,
    agent_run_in_collection: AgentRun,
    agent_run_in_second_collection: AgentRun,
    test_result_set_id: str,
) -> None:
    """submit_requests fails when one item in a bulk submission is invalid."""
    from docent.sdk.llm_context import Prompt
    from docent.sdk.llm_request import LLMRequest

    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)

    # First request is valid
    valid_prompt = Prompt(
        [
            AgentRunRef(id=agent_run_in_collection.id, collection_id=test_collection_id),
            "Analyze this agent run.",
        ]
    )
    valid_request = LLMRequest(prompt=valid_prompt)

    # Second request has an item from the wrong collection
    invalid_prompt = Prompt(
        [
            AgentRunRef(id=agent_run_in_second_collection.id, collection_id=test_collection_id),
            "Analyze this agent run.",
        ]
    )
    invalid_request = LLMRequest(prompt=invalid_prompt)

    # Submit both - should fail because of the invalid one
    with pytest.raises(ValueError, match="belongs to collection"):
        await result_set_service.submit_requests(
            ctx=ctx,
            result_set_id=test_result_set_id,
            requests=[valid_request, invalid_request],
        )
