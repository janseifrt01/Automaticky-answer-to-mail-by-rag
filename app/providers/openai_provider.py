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
    ) -> None:
        self._api_key = api_key
        self._embedding_model = embedding_model
        self._generation_model = generation_model
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        """Lazily construct the OpenAI client on first use."""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)
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


def build_openai_provider(settings) -> OpenAIProvider:
    """Construct an :class:`OpenAIProvider` from app settings."""
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        embedding_model=settings.embedding_model,
        generation_model=settings.generation_model,
    )


__all__ = ["OpenAIProvider", "build_openai_provider"]
