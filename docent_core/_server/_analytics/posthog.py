import os
from typing import Any, Dict, Optional

from posthog import Posthog

from docent._log_util import get_logger
from docent_core._db_service.schemas.auth_models import User
from docent_core._env_util import get_deployment_id

logger = get_logger(__name__)

POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY")


class AnalyticsClient:
    def __init__(self):
        if get_deployment_id():
            if not POSTHOG_API_KEY:
                raise ValueError("POSTHOG_API_KEY is required for prod and staging, but is not set")
            self.ph = Posthog(project_api_key=POSTHOG_API_KEY, host="https://us.i.posthog.com")
        else:
            self.ph = None

    def identify_user(self, user: Optional[User]) -> Optional[str]:
        """
        Identify user in PostHog and return distinct_id.

        Args:
            user: User object or None for anonymous users

        Returns:
            distinct_id for PostHog events
        """
        if not self.ph:
            return None

        # Do not identify anonymous users
        if not user:
            return None

        self.ph.capture(
            event="$set",
            distinct_id=user.id,
            properties={
                "$set": {
                    "email": user.email,
                    "is_anonymous": user.is_anonymous,
                },
            },
        )
        return user.id

    def track_event(self, event_name: str, properties: Optional[Dict[str, Any]] = None) -> None:
        """
        Track an event in ph.
        Should be called within a Posthog context.

        Args:
            event_name: Name of the event
            properties: Additional event properties
        """
        if not self.ph:
            logger.warning("PostHog client not initialized, skipping event tracking")
            return

        event_properties = properties or {}
        self.ph.capture(event=event_name, properties=event_properties)
