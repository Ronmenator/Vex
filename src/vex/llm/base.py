"""LLM client protocol and message types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable


@dataclass(frozen=True)
class Message:
    """A single message in an LLM conversation."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # For tool result messages


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolDefinition:
    """Tool definition sent to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class LlmResponse:
    """Complete (non-streaming) response from an LLM."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop" | "tool_use" | "length"
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class StreamEvent:
    """A single event from a streaming LLM response."""

    text_delta: str | None = None
    tool_call: ToolCall | None = None  # Complete tool call when fully assembled
    done: bool = False
    finish_reason: str | None = None


@runtime_checkable
class LlmClient(Protocol):
    """Protocol for LLM providers."""

    @property
    def provider_name(self) -> str: ...

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LlmResponse: ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]: ...
