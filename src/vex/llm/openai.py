"""OpenAI-compatible LLM provider (works with OpenAI, LM Studio, etc.)."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import openai

from .base import LlmResponse, Message, StreamEvent, ToolCall, ToolDefinition


class OpenAiClient:
    """LLM client for OpenAI and OpenAI-compatible APIs."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
        base_url: str | None = None,
        max_tokens: int = 8192,
    ):
        self._model = model
        self._max_tokens = max_tokens
        self._client = openai.AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LlmResponse:
        api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools) if tools else None

        params: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "messages": api_messages,
        }
        if api_tools:
            params["tools"] = api_tools

        response = await self._client.chat.completions.create(**params)

        choice = response.choices[0]
        content = choice.message.content
        tool_calls: list[ToolCall] = []

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )

        finish_reason = "tool_use" if choice.finish_reason == "tool_calls" else "stop"

        return LlmResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        api_messages = self._convert_messages(messages)
        api_tools = self._convert_tools(tools) if tools else None

        params: dict[str, Any] = {
            "model": kwargs.get("model", self._model),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "messages": api_messages,
            "stream": True,
        }
        if api_tools:
            params["tools"] = api_tools

        # Track tool call assembly
        tool_call_parts: dict[int, dict[str, str]] = {}

        stream = await self._client.chat.completions.create(**params)

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            if delta.content:
                yield StreamEvent(text_delta=delta.content)

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_parts:
                        tool_call_parts[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    part = tool_call_parts[idx]
                    if tc_delta.id:
                        part["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            part["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            part["arguments"] += tc_delta.function.arguments

            if finish_reason:
                # Emit completed tool calls
                for idx in sorted(tool_call_parts.keys()):
                    part = tool_call_parts[idx]
                    try:
                        args = json.loads(part["arguments"]) if part["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    yield StreamEvent(
                        tool_call=ToolCall(
                            id=part["id"], name=part["name"], arguments=args
                        )
                    )
                tool_call_parts.clear()

                yield StreamEvent(
                    done=True,
                    finish_reason="tool_use" if finish_reason == "tool_calls" else "stop",
                )

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert to OpenAI API format."""
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "tool":
                api_messages.append(
                    {
                        "role": "tool",
                        "content": msg.content or "",
                        "tool_call_id": msg.tool_call_id or "",
                    }
                )
            elif msg.role == "assistant" and msg.tool_calls:
                api_tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
                api_messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": api_tool_calls,
                    }
                )
            else:
                api_messages.append(
                    {"role": msg.role, "content": msg.content or ""}
                )

        return api_messages

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Convert to OpenAI tool format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
