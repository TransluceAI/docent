import os
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel

from docent_core.investigator.db.schemas.experiment import SQLAOpenAICompatibleBackend


class ModelWithClient(BaseModel):
    """
    Instantiated model with a client, useful for packaging these together.
    TODO: maybe add sampling parameters to the model (e.g. temperature, max_tokens, etc.)
    """

    model_config = {"arbitrary_types_allowed": True}

    client: AsyncOpenAI
    model: str


class OpenAICompatibleBackendConfig(BaseModel):
    """OpenAI compatible backend."""

    id: str
    name: str
    provider: str
    model: str
    api_key: Optional[str]
    base_url: Optional[str]

    @classmethod
    def from_sql(cls, backend: SQLAOpenAICompatibleBackend) -> "OpenAICompatibleBackendConfig":
        return cls(
            id=backend.id,
            name=backend.name,
            provider=backend.provider,
            model=backend.model,
            api_key=backend.api_key,
            base_url=backend.base_url,
        )

    def build_client(self) -> ModelWithClient:
        # only use our API keys for these providers (to avoid leaking them to other backends)!
        # TODO: add support for users to set their own API keys?

        if self.provider == "openai":
            assert self.base_url == "https://api.openai.com/v1/"
            assert self.api_key is None

            client = AsyncOpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=self.base_url,
            )
        elif self.provider == "anthropic":
            assert self.base_url == "https://api.anthropic.com/v1/"
            assert self.api_key is None

            client = AsyncOpenAI(
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                base_url=self.base_url,
            )
        elif self.provider == "google":
            assert self.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
            assert self.api_key is None

            client = AsyncOpenAI(
                api_key=os.getenv("GOOGLE_API_KEY"),
                base_url=self.base_url,
            )
        elif self.provider == "openrouter":
            assert self.base_url == "https://openrouter.ai/api/v1"
            assert self.api_key is None

            client = AsyncOpenAI(
                api_key=os.getenv("OPENROUTER_API_KEY"),
                base_url=self.base_url,
            )

        else:
            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

        return ModelWithClient(client=client, model=self.model)
