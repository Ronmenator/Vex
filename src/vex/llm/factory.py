"""LLM provider factory — creates clients from config."""

from __future__ import annotations

from typing import Any

from .anthropic import AnthropicClient
from .base import LlmClient
from .ollama import OllamaClient
from .openai import OpenAiClient


def create_llm_client(
    config: dict[str, Any],
    provider_override: str | None = None,
    model_override: str | None = None,
) -> LlmClient:
    """Create an LLM client from configuration.

    Config expects:
        provider: str  — "anthropic", "openai", "ollama"
        model: str     — model name
        Plus provider-specific keys under config[provider].

    Overrides allow sub-agents to use different providers/models.
    """
    provider = provider_override or config.get("provider", "anthropic")
    model = model_override or config.get("model", "claude-sonnet-4-20250514")

    if provider == "anthropic":
        provider_config = config.get("anthropic", {})
        return AnthropicClient(
            api_key=provider_config.get("api_key"),
            model=model,
            max_tokens=provider_config.get("max_tokens", 8192),
        )

    if provider == "openai":
        provider_config = config.get("openai", {})
        return OpenAiClient(
            api_key=provider_config.get("api_key"),
            model=model,
            base_url=provider_config.get("base_url"),
            max_tokens=provider_config.get("max_tokens", 8192),
        )

    if provider == "ollama":
        provider_config = config.get("ollama", {})
        return OllamaClient(
            model=model,
            base_url=provider_config.get("base_url", "http://localhost:11434/v1"),
            max_tokens=provider_config.get("max_tokens", 8192),
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
