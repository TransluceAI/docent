from sqlalchemy.ext.asyncio import AsyncSession

from docent_core.docent.services.monoservice import MonoService


class SetupService:
    def __init__(self, session: AsyncSession, service: MonoService):
        self.session = session
        self.service = service

    async def setup_dummy_user(self) -> dict[str, str | None]:
        """
        Set up dummy data for development including:
        - A dummy user with email/password
        - API keys for the dummy user
        - A default collection with proper permissions

        Returns a dictionary with created resource IDs and credentials.
        This method is idempotent - it will not create duplicates if run multiple times.
        """
        dummy_email = "a@b.com"
        dummy_password = "1234"
        dummy_collection_name = "Development Collection"
        dummy_collection_description = "Default collection for development and testing"
        api_key_name = "Development API Key"

        result: dict[str, str | None] = {}

        existing_user = await self.service.get_user_by_email(dummy_email)
        if existing_user:
            result["user_id"] = str(existing_user.id)
            result["user_email"] = dummy_email
            result["message"] = "Dummy user already exists"
        else:
            user = await self.service.create_user(dummy_email, dummy_password)
            result["user_id"] = str(user.id)
            result["user_email"] = user.email
            result["user_password"] = dummy_password
            result["message"] = "Created new dummy user"

        api_key_id, raw_api_key = await self.service.create_api_key(result["user_id"], api_key_name)
        result["api_key_id"] = api_key_id
        result["api_key"] = raw_api_key

        user_obj = await self.service.get_user_by_email(dummy_email)
        if user_obj is None:
            raise RuntimeError(f"Failed to retrieve user with email {dummy_email}")

        collection_id = await self.service.create_collection(
            user=user_obj,
            name=dummy_collection_name,
            description=dummy_collection_description,
        )
        result["collection_id"] = str(collection_id)
        result["collection_name"] = dummy_collection_name

        return result
