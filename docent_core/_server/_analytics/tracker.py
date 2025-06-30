"""Analytics tracking utilities for router endpoint usage."""

from typing import Optional

from docent_core._db_service.schemas.auth_models import User
from docent_core._db_service.schemas.tables import EndpointType, SQLAAnalyticsEvent
from docent_core._db_service.service import DBService


def extract_user_id(user: Optional[User]) -> Optional[str]:
    """Extract user ID from a User object, handling None cases."""
    return user.id if user else None


async def track_endpoint_usage(
    db: DBService,
    endpoint: EndpointType,
    collection_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Track usage of a router endpoint.

    Args:
        db: Database service instance
        endpoint: The endpoint that was called
        collection_id: Optional collection ID (None if endpoint doesn't operate on a specific collection)
        user_id: Optional user ID (None for anonymous users)
    """
    try:
        # Create the analytics event
        event = SQLAAnalyticsEvent.create_event(
            endpoint=endpoint,
            collection_id=collection_id,
            user_id=user_id,
        )

        # Save to database
        async with db.session() as session:
            session.add(event)
            await session.commit()

    except Exception as e:
        # Log the error but don't fail the main request
        # We don't want analytics tracking to break the user experience
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to track analytics event for {endpoint}: {e}")


async def track_endpoint_with_user(
    db: DBService,
    endpoint: EndpointType,
    user: Optional[User] = None,
    collection_id: Optional[str] = None,
) -> None:
    """
    Convenience function to track endpoint usage with a User object.

    Args:
        db: Database service instance
        endpoint: The endpoint that was called
        user: Optional User object (None for anonymous users)
        collection_id: Optional collection ID
    """
    user_id = extract_user_id(user)
    await track_endpoint_usage(db, endpoint, collection_id, user_id)
