from datetime import UTC, datetime
from typing import AsyncContextManager, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent_core.docent.db.schemas.tables import SQLAUserProfile
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


class OnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        service: MonoService,
    ):
        self.session = session
        self.session_cm_factory = session_cm_factory
        self.service = service

    async def get_user_profile(self, user_id: str) -> SQLAUserProfile | None:
        """Get existing onboarding data for a user."""
        result = await self.session.execute(
            select(SQLAUserProfile).where(SQLAUserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def save_user_profile(
        self,
        user_id: str,
        institution: str | None = None,
        task: str | None = None,
        help_type: str | None = None,
        frameworks: dict[str, list[str]] | None = None,
        providers: dict[str, list[str]] | None = None,
        discovery_source: str | None = None,
    ) -> SQLAUserProfile:
        """Save or update onboarding data for a user."""
        # Check if user profile already exists
        existing = await self.get_user_profile(user_id)

        if existing:
            # Update existing record
            existing.institution = institution
            existing.task = task
            existing.help_type = help_type
            existing.frameworks = frameworks
            existing.providers = providers
            existing.discovery_source = discovery_source
            existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await self.session.commit()
            return existing
        else:
            # Create new record
            user_profile = SQLAUserProfile(
                user_id=user_id,
                institution=institution,
                task=task,
                help_type=help_type,
                frameworks=frameworks,
                providers=providers,
                discovery_source=discovery_source,
            )
            self.session.add(user_profile)
            await self.session.commit()
            return user_profile
