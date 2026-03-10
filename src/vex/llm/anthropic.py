"""Anthropic Claude LLM provider."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import anthropic

from .base import LlmResponse, Message, StreamEvent, ToolCall, ToolDefinition


class AnthropicClient:
    """LLM client for Anthropic Claude models."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
    ):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LlmResponse:
        system, api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools) if tools else []

        params: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "messages": api_messages,
        }
        if system:
            params["system"] = system
        if api_tools:
            params["tools"] = api_tools

        response = await self._client.messages.create(**params)

        content_text = ""
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        finish_reason = "tool_use" if response.stop_reason == "tool_use" else "stop"

        return LlmResponse(
            content=content_text or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        system, api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools) if tools else []

        params: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "messages": api_messages,
        }
        if system:
            params["system"] = system
        if api_tools:
            params["tools"] = api_tools

        # Track tool call assembly during streaming
        current_tool_id: str | None = None
        current_tool_name: str | None = None
        current_tool_json = ""

        async with self._client.messages.stream(**params) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_id = block.id
                        current_tool_name = block.name
                        current_tool_json = ""

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield StreamEvent(text_delta=delta.text)
                    elif delta.type == "input_json_delta":
                        current_tool_json += delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_id and current_tool_name:
                        try:
                            args = json.loads(current_tool_json) if current_tool_json else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield StreamEvent(
                            tool_call=ToolCall(
                                id=current_tool_id,
                                name=current_tool_name,
                                arguments=args,
                            )
                        )
                        current_tool_id = None
                        current_tool_name = None
                        current_tool_json = ""

                elif event.type == "message_stop":
                    pass

                elif event.type == "message_delta":
                    stop_reason = getattr(event.delta, "stop_reason", None)
                    if stop_reason:
                        yield StreamEvent(
                            done=True,
                            finish_reason="tool_use" if stop_reason == "tool_use" else "stop",
                        )

    def _convert_messages(
        self, messages: list[Message]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert our Message types to Anthropic API format.

        Extracts system messages and converts the rest to Anthropic's content block format.
        """
        system: str | None = None
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system = msg.content
                continue

            if msg.role == "tool":
                api_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content or "",
                            }
                        ],
                    }
                )
                continue

            if msg.role == "assistant" and msg.tool_calls:
                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                api_messages.append({"role": "assistant", "content": content})
                continue

            api_messages.append({"role": msg.role, "content": msg.content or ""})

        return system, api_messages

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert our ToolDefinition to Anthropic tool format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]
