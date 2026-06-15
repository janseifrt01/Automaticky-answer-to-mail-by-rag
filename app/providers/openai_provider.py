"""OpenAI implementation of the embedding + generation providers.

Import-safe without network access: the OpenAI client is created lazily on
first use, so constructing ``OpenAIProvider`` (and importing this module)
never performs I/O or requires a live key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI


class OpenAIProvider:
    """Embeddings via the embeddings API, generation via chat completions."""

    def __init__(
        self,
        api_key: str,
        embedding_model: str,
        generation_model: str,
        *,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._embedding_model = embedding_model
        self._generation_model = generation_model
        self._base_url = base_url
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        """Lazily construct the OpenAI client on first use."""
        if self._client is None:
            from openai import OpenAI

            kwargs: dict = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(
            model=self._embedding_model,
            input=texts,
        )
        return [item.embedding for item in resp.data]

    def generate(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
    ) -> str:
        kwargs: dict = {
            "model": self._generation_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": json_schema,
            }
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


def build_openai_provider(
    settings, *, generation_model: str | None = None
) -> OpenAIProvider:
    """Construct an :class:`OpenAIProvider` from app settings."""
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        embedding_model=settings.embedding_model,
        generation_model=generation_model or settings.generation_model,
    )


def build_github_models_provider(
    settings, *, generation_model: str | None = None
) -> OpenAIProvider:
    """GitHub Models is OpenAI-compatible — point the client at its base URL."""
    return OpenAIProvider(
        api_key=settings.github_token,
        embedding_model=settings.github_models_embedding_model,
        generation_model=generation_model or settings.github_models_generation_model,
        base_url=settings.github_models_base_url,
    )


__all__ = ["OpenAIProvider", "build_openai_provider", "build_github_models_provider"]
