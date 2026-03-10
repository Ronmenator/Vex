"""Ollama LLM provider — local models via the OpenAI-compatible API."""

from __future__ import annotations

from typing import Any, AsyncIterator

from .base import LlmResponse, Message, StreamEvent, ToolDefinition
from .openai import OpenAiClient


class OllamaClient(OpenAiClient):
    """LLM client for Ollama (uses OpenAI-compatible API)."""

    def __init__(
        self,
        model: str = "llama3.1",
        base_url: str = "http://localhost:11434/v1",
        max_tokens: int = 8192,
    ):
        super().__init__(
            api_key="ollama",  # Ollama doesn't need a real key
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
        )

    @property
    def provider_name(self) -> str:
        return "ollama"
