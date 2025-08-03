from typing import Any, Dict, Optional

from posthog import Posthog

from docent._log_util import get_logger
from docent_core._db_service.schemas.auth_models import User
from docent_core._env_util import ENV, get_deployment_id

logger = get_logger(__name__)


class AnalyticsClient:
    def __init__(self):
        if deployment_id := get_deployment_id():
            api_key = ENV.get("POSTHOG_API_KEY")
            if not api_key:
                raise ValueError(f"POSTHOG_API_KEY is required for {deployment_id}, but is not set")
            self.ph = Posthog(project_api_key=api_key, host="https://us.i.posthog.com")
            logger.info(f"PostHog client initialized for {deployment_id}")
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
