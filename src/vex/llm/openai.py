"""OpenAI-compatible LLM provider (works with OpenAI, LM Studio, etc.)."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import openai

from .base import LlmResponse, Message, StreamEvent, ToolCall, ToolDefinition

# Models that require the Responses API instead of Chat Completions.
# Match by prefix so future sub-versions are covered automatically.
_RESPONSES_API_PREFIXES = (
    "o1", "o3", "o4",
    "gpt-4.1", "gpt-4.5",
    "gpt-5",
)


def _uses_responses_api(model: str) -> bool:
    m = model.lower()
    return any(m == p or m.startswith(p + "-") or m.startswith(p + ".") for p in _RESPONSES_API_PREFIXES)


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
        model = kwargs.get("model", self._model)
        if _uses_responses_api(model):
            return await self._chat_responses(messages, tools, model, **kwargs)
        return await self._chat_completions(messages, tools, model, **kwargs)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        model = kwargs.get("model", self._model)
        if _uses_responses_api(model):
            async for event in self._stream_responses(messages, tools, model, **kwargs):
                yield event
        else:
            async for event in self._stream_completions(messages, tools, model, **kwargs):
                yield event

    # ── Responses API ──────────────────────────────────────────────────────────

    async def _chat_responses(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        model: str,
        **kwargs: Any,
    ) -> LlmResponse:
        params: dict[str, Any] = {
            "model": model,
            "input": self._convert_messages(messages, responses_api=True),
            "max_output_tokens": kwargs.get("max_tokens", self._max_tokens),
        }
        if tools:
            params["tools"] = self._convert_tools_responses(tools)

        response = await self._client.responses.create(**params)

        content = ""
        tool_calls: list[ToolCall] = []

        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    if hasattr(part, "text"):
                        content += part.text
            elif item.type == "function_call":
                try:
                    args = json.loads(item.arguments) if item.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                name = self._restore_tool_name(item.name, tools or [])
                tool_calls.append(ToolCall(id=item.call_id, name=name, arguments=args))

        finish_reason = "tool_use" if tool_calls else "stop"
        usage = getattr(response, "usage", None)
        return LlmResponse(
            content=content or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            prompt_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )

    async def _stream_responses(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": model,
            "input": self._convert_messages(messages, responses_api=True),
            "max_output_tokens": kwargs.get("max_tokens", self._max_tokens),
        }
        if tools:
            params["tools"] = self._convert_tools_responses(tools)

        # Accumulate tool calls across streaming events
        tool_call_parts: dict[str, dict[str, str]] = {}  # call_id -> {name, arguments}
        # Map output_index -> call_id (delta events don't carry call_id)
        index_to_call_id: dict[int, str] = {}

        async with self._client.responses.stream(**params) as stream:
            async for event in stream:
                etype = getattr(event, "type", "")

                if etype == "response.output_text.delta":
                    yield StreamEvent(text_delta=event.delta)

                elif etype == "response.function_call_arguments.delta":
                    # Delta events have output_index but not call_id
                    output_index = getattr(event, "output_index", 0)
                    call_id = index_to_call_id.get(output_index)
                    if call_id and call_id in tool_call_parts:
                        tool_call_parts[call_id]["arguments"] += event.delta

                elif etype == "response.output_item.added":
                    item = getattr(event, "item", None)
                    if item and getattr(item, "type", "") == "function_call":
                        call_id = item.call_id
                        output_index = getattr(event, "output_index", 0)
                        index_to_call_id[output_index] = call_id
                        sanitized = item.name
                        if call_id not in tool_call_parts:
                            tool_call_parts[call_id] = {"name": sanitized, "arguments": ""}
                        else:
                            tool_call_parts[call_id]["name"] = sanitized

                elif etype == "response.completed":
                    for call_id, part in tool_call_parts.items():
                        try:
                            args = json.loads(part["arguments"]) if part["arguments"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        name = self._restore_tool_name(part["name"], tools or [])
                        yield StreamEvent(
                            tool_call=ToolCall(id=call_id, name=name, arguments=args)
                        )

                    finish = "tool_use" if tool_call_parts else "stop"
                    yield StreamEvent(done=True, finish_reason=finish)

    # ── Chat Completions API ────────────────────────────────────────────────────

    async def _chat_completions(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        model: str,
        **kwargs: Any,
    ) -> LlmResponse:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "messages": self._convert_messages(messages),
        }
        if tools:
            params["tools"] = self._convert_tools(tools)

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
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        finish_reason = "tool_use" if choice.finish_reason == "tool_calls" else "stop"
        return LlmResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
        )

    async def _stream_completions(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
            "messages": self._convert_messages(messages),
            "stream": True,
        }
        if tools:
            params["tools"] = self._convert_tools(tools)

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
                        tool_call_parts[idx] = {"id": "", "name": "", "arguments": ""}
                    part = tool_call_parts[idx]
                    if tc_delta.id:
                        part["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            part["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            part["arguments"] += tc_delta.function.arguments

            if finish_reason:
                for idx in sorted(tool_call_parts.keys()):
                    part = tool_call_parts[idx]
                    try:
                        args = json.loads(part["arguments"]) if part["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    yield StreamEvent(
                        tool_call=ToolCall(id=part["id"], name=part["name"], arguments=args)
                    )
                tool_call_parts.clear()
                yield StreamEvent(
                    done=True,
                    finish_reason="tool_use" if finish_reason == "tool_calls" else "stop",
                )

    # ── Conversion helpers ──────────────────────────────────────────────────────

    def _convert_messages(self, messages: list[Message], responses_api: bool = False) -> list[dict[str, Any]]:
        """Convert to OpenAI message format."""
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "tool":
                if responses_api:
                    # Responses API uses function_call_output items
                    api_messages.append({
                        "type": "function_call_output",
                        "call_id": msg.tool_call_id or "",
                        "output": msg.content or "",
                    })
                else:
                    api_messages.append({
                        "role": "tool",
                        "content": msg.content or "",
                        "tool_call_id": msg.tool_call_id or "",
                    })
            elif msg.role == "assistant" and msg.tool_calls:
                if responses_api:
                    # Responses API: emit one function_call item per tool call
                    for tc in msg.tool_calls:
                        api_messages.append({
                            "type": "function_call",
                            "call_id": tc.id,
                            "name": self._sanitize_tool_name(tc.name),
                            "arguments": json.dumps(tc.arguments),
                        })
                else:
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
                    api_messages.append({
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": api_tool_calls,
                    })
            else:
                api_messages.append({"role": msg.role, "content": msg.content or ""})

        return api_messages

    def _convert_tools(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Chat Completions tool format."""
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

    @staticmethod
    def _sanitize_tool_name(name: str) -> str:
        """Responses API only allows [a-zA-Z0-9_-] in tool names."""
        return name.replace(".", "_")

    @staticmethod
    def _restore_tool_name(sanitized: str, tools: list[ToolDefinition]) -> str:
        """Map a sanitized name back to the original tool name."""
        for t in tools:
            if OpenAiClient._sanitize_tool_name(t.name) == sanitized:
                return t.name
        return sanitized

    def _convert_tools_responses(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
        """Responses API tool format (name at top level, sanitized)."""
        return [
            {
                "type": "function",
                "name": self._sanitize_tool_name(t.name),
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in tools
        ]
