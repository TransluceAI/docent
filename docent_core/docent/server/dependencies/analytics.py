from typing import AsyncGenerator

from fastapi import Depends

from docent_core._server._analytics.posthog import AnalyticsClient
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.server.dependencies.user import get_user_anonymous_ok


async def use_posthog_user_context(
    user: User = Depends(get_user_anonymous_ok),
) -> AsyncGenerator[AnalyticsClient, None]:
    client = AnalyticsClient()
    with client.user_context(user):
        yield client
