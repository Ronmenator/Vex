"""Test harness — mock LLM client and tool testing utilities."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from vex.llm.base import LlmResponse, Message, StreamEvent, ToolCall, ToolDefinition
from vex.tools.base import Tool, ToolContext, ToolResult


class MockLlmClient:
    """Deterministic LLM client for testing."""

    def __init__(self, responses: list[str | list[ToolCall]] | None = None) -> None:
        self._responses = responses or []
        self._call_index = 0
        self._calls: list[dict[str, Any]] = []

    def add_response(self, text: str) -> None:
        """Add a text response."""
        self._responses.append(text)

    def add_tool_response(self, tool_calls: list[ToolCall]) -> None:
        """Add a response that includes tool calls."""
        self._responses.append(tool_calls)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LlmResponse:
        self._calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})

        if self._call_index >= len(self._responses):
            return LlmResponse(content="No more mock responses.", tool_calls=[])

        response = self._responses[self._call_index]
        self._call_index += 1

        if isinstance(response, str):
            return LlmResponse(content=response, tool_calls=[])
        else:
            return LlmResponse(content=None, tool_calls=response)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        self._calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})

        if self._call_index >= len(self._responses):
            yield StreamEvent(text_delta="No more mock responses.", done=True)
            return

        response = self._responses[self._call_index]
        self._call_index += 1

        if isinstance(response, str):
            # Yield text in chunks
            for i in range(0, len(response), 20):
                chunk = response[i : i + 20]
                yield StreamEvent(text_delta=chunk)
            yield StreamEvent(done=True, finish_reason="end_turn")
        else:
            # Yield tool calls
            for tc in response:
                yield StreamEvent(tool_call=tc)
            yield StreamEvent(done=True, finish_reason="tool_use")

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._calls

    @property
    def provider_name(self) -> str:
        return "mock"

    def reset(self) -> None:
        self._call_index = 0
        self._calls.clear()


class ToolTestHarness:
    """Utility for testing tools in isolation."""

    def __init__(
        self,
        workspace_root: str = "/tmp/vex_test",
        agent_id: str = "test-agent",
    ) -> None:
        self._workspace = workspace_root
        self._agent_id = agent_id

    def make_context(self, dry_run: bool = False) -> ToolContext:
        """Create a ToolContext for testing."""
        return ToolContext(
            workspace_root=self._workspace,
            correlation_id="test-correlation",
            agent_id=self._agent_id,
            dry_run=dry_run,
        )

    async def execute(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        dry_run: bool = False,
    ) -> ToolResult:
        """Execute a tool with a test context."""
        ctx = self.make_context(dry_run=dry_run)
        return await tool.execute(arguments, ctx)


class AgentTestHarness:
    """Utility for testing full agent conversations."""

    def __init__(self) -> None:
        self.llm = MockLlmClient()
        self._results: list[Any] = []

    async def run_turn(
        self,
        agent_loop: Any,
        user_message: str,
        conversation: Any,
    ) -> tuple[str, list[Any]]:
        """Run a single turn and collect all events.

        Returns (response_text, tool_events).
        """
        from vex.agent.loop import ToolCallEvent

        text_parts: list[str] = []
        tool_events: list[Any] = []

        async for event in agent_loop.run(user_message, conversation):
            if isinstance(event, StreamEvent) and event.text_delta:
                text_parts.append(event.text_delta)
            elif isinstance(event, ToolCallEvent):
                tool_events.append(event)

        return "".join(text_parts), tool_events
