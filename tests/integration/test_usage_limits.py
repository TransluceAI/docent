"""Integration tests for usage limit functionality."""

from datetime import UTC, datetime, timedelta
from typing import Any, AsyncContextManager, Callable
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.data_models.exceptions import DocentUsageLimitException
from docent._llm_util.data_models.llm_output import LLMCompletion, LLMOutput
from docent._llm_util.llm_svc import MessagesInput
from docent._llm_util.providers.preference_types import ModelOption
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.db.schemas.tables import SQLAModelApiKey, SQLAModelUsage
from docent_core.docent.services.llms import LLMService
from docent_core.docent.services.usage import UsageService

PLATFORM_MODEL = ModelOption(provider="anthropic", model_name="claude-sonnet-4")

TEST_INPUTS: list[MessagesInput] = [[{"role": "user", "content": "Hello, world!"}]]


# Helper functions
async def create_byok_key(db_session: AsyncSession, user: User, provider: str = "anthropic") -> str:
    """Create a BYOK key for testing."""
    api_key = SQLAModelApiKey(
        id=str(uuid4()), user_id=user.id, provider=provider, api_key=f"test-{provider}-key-123"
    )
    db_session.add(api_key)
    await db_session.commit()
    return api_key.api_key


def mock_usage_check(within_limit: bool) -> Any:
    """Context manager to mock usage limit checks."""
    return patch(
        "docent_core.docent.services.llms.check_spend_within_limit", return_value=within_limit
    )


def mock_llm_call() -> Any:
    """Context manager to mock LLM API calls."""
    success_response = [
        LLMOutput(
            model="claude-sonnet-4",
            completions=[
                LLMCompletion(text="Hello! How can I help you today?", finish_reason="stop")
            ],
        )
    ]
    return patch(
        "docent._llm_util.llm_svc.BaseLLMService.get_completions", return_value=success_response
    )


def assert_blocked_by_usage_limit(outputs: list[LLMOutput]) -> None:
    """Assert that outputs contain usage limit exception."""
    assert len(outputs) == 1
    output = outputs[0]
    assert len(output.completions) == 0
    assert len(output.errors) == 1
    assert isinstance(output.errors[0], DocentUsageLimitException)


def assert_successful_completion(
    outputs: list[LLMOutput], expected_text: str = "Hello! How can I help you today?"
) -> None:
    """Assert that outputs contain successful completion."""
    assert len(outputs) == 1
    output = outputs[0]
    assert len(output.completions) == 1
    assert output.completions[0].text == expected_text
    assert len(output.errors) == 0


# Tests
@pytest.mark.integration
async def test_usage_limit_blocks_platform_providers(
    db_session: AsyncSession,
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    test_user: User,
) -> None:
    """Users over usage limit get blocked when using platform providers."""
    llm_service = LLMService(session_cm_factory, test_user, UsageService(session_cm_factory))

    with mock_usage_check(within_limit=False):
        outputs = await llm_service.get_completions(
            inputs=TEST_INPUTS, model_options=[PLATFORM_MODEL], max_new_tokens=100
        )

    assert_blocked_by_usage_limit(outputs)
    assert (
        outputs[0].errors[0].user_message
        == "Free daily usage limit reached. Add your own API key in settings or contact us for increased limits."
    )


@pytest.mark.integration
async def test_usage_limit_allows_when_under_limit(
    db_session: AsyncSession,
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    test_user: User,
) -> None:
    """Users under usage limit can proceed normally."""
    llm_service = LLMService(session_cm_factory, test_user, UsageService(session_cm_factory))

    with mock_usage_check(within_limit=True), mock_llm_call() as mock_llm:
        outputs = await llm_service.get_completions(
            inputs=TEST_INPUTS, model_options=[PLATFORM_MODEL], max_new_tokens=100
        )

    assert_successful_completion(outputs)
    mock_llm.assert_called_once()


@pytest.mark.integration
async def test_byok_users_bypass_usage_limits(
    db_session: AsyncSession,
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    test_user: User,
) -> None:
    """BYOK users bypass usage limits even when over free cap."""
    api_key = await create_byok_key(db_session, test_user)
    llm_service = LLMService(session_cm_factory, test_user, UsageService(session_cm_factory))
    model_options = [ModelOption(provider="anthropic", model_name="claude-sonnet-4")]

    with mock_usage_check(within_limit=False), mock_llm_call() as mock_llm:
        outputs = await llm_service.get_completions(
            inputs=TEST_INPUTS, model_options=model_options, max_new_tokens=100
        )

    assert_successful_completion(outputs)
    mock_llm.assert_called_once()
    assert mock_llm.call_args.kwargs["_api_key_overrides"] == {"anthropic": api_key}


@pytest.mark.integration
async def test_old_usage_outside_window_not_counted(
    db_session: AsyncSession,
    session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
    test_user: User,
) -> None:
    """Usage outside the 24-hour window doesn't count toward limits."""
    # Insert high usage from 25 hours ago (outside window)
    old_timestamp = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
    high_usage = SQLAModelUsage(
        id=str(uuid4()),
        user_id=test_user.id,
        api_key_id=None,
        model={"model_name": "claude-sonnet-4"},
        bucket_start=old_timestamp.replace(second=0, microsecond=0),
        metric_name="input",
        value=1_000_000,  # Would cost ~$300 if counted
    )
    db_session.add(high_usage)
    await db_session.commit()

    llm_service = LLMService(session_cm_factory, test_user, UsageService(session_cm_factory))
    usage_service = UsageService(session_cm_factory)
    model_options = [ModelOption(provider="anthropic", model_name="claude-sonnet-4")]

    with mock_llm_call() as mock_llm:
        outputs = await llm_service.get_completions(
            inputs=TEST_INPUTS, model_options=model_options, max_new_tokens=100
        )

    assert_successful_completion(outputs)
    mock_llm.assert_called_once()

    # Verify current usage is $0
    current_spend = await usage_service.get_free_spend_cents(test_user.id, 24 * 60 * 60)
    assert current_spend == 0
