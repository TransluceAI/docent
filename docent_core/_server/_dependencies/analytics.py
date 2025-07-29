from typing import AsyncGenerator

from fastapi import Depends
from posthog import identify_context, new_context

from docent_core._db_service.schemas.auth_models import User
from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core._server._dependencies.user import get_user_anonymous_ok


async def use_posthog_user_context(
    user: User = Depends(get_user_anonymous_ok),
) -> AsyncGenerator[AnalyticsClient, None]:
    client = AnalyticsClient()

    # Register the user with PostHog
    # TODO(mengk): I think this makes lots of extraneous calls
    distinct_id = client.identify_user(user)

    with new_context():
        # Anything in this context will be associated with the user
        if distinct_id:
            identify_context(distinct_id)
        yield client
