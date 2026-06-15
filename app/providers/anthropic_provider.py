"""Anthropic (Claude) implementation of the generation provider.

Generation only — Anthropic has no embeddings API, so KB embeddings are paired
from another provider via :class:`CompositeProvider`. Import-safe without the SDK
or a key: the client is built lazily on the first ``generate`` call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import Anthropic

_MAX_TOKENS = 4096


class AnthropicProvider:
    """Generates replies via the Claude Messages API (Haiku by default)."""

    def __init__(self, api_key: str, generation_model: str) -> None:
        self._api_key = api_key
        self._generation_model = generation_model
        self._client: Anthropic | None = None

    @property
    def client(self) -> Anthropic:
        """Lazily construct the Anthropic client on first use."""
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self._api_key)
        return self._client

    def generate(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict | None = None,
    ) -> str:
        kwargs: dict = {
            "model": self._generation_model,
            "max_tokens": _MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if json_schema is not None:
            # Callers pass an OpenAI-style {"name", "schema", "strict"} wrapper;
            # Anthropic's output_config wants the bare JSON Schema.
            schema = json_schema.get("schema", json_schema)
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }
        resp = self.client.messages.create(**kwargs)
        return "".join(
            block.text
            for block in resp.content
            if getattr(block, "type", None) == "text"
        )


def build_anthropic_provider(
    settings, *, generation_model: str | None = None
) -> AnthropicProvider:
    """Construct an :class:`AnthropicProvider` from app settings."""
    return AnthropicProvider(
        api_key=settings.anthropic_api_key,
        generation_model=generation_model or settings.anthropic_model,
    )


__all__ = ["AnthropicProvider", "build_anthropic_provider"]
