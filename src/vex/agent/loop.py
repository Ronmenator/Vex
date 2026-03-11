"""Core agent loop — the heart of Vex.

Receives a user message, calls the LLM with tool definitions, executes tool calls,
feeds results back, and repeats until the LLM produces a final text response.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable

from vex.llm.base import (
    LlmClient,
    Message,
    StreamEvent,
    ToolCall,
    ToolDefinition,
)
from vex.audit.log import AuditLog
from vex.debug.mode import DebugMode
from vex.metrics.collector import MetricsCollector, ToolMetric
from vex.safety.conflict import ConflictDetector
from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema
from vex.tools.middleware import ToolExecutor
from vex.tools.registry import ToolRegistry

from .conversation import Conversation
from .definition import AgentDefinition, DEFAULT_SYSTEM_PROMPT


class ToolCallEvent:
    """Event emitted during tool execution for the CLI to render."""

    def __init__(
        self,
        tool_call: ToolCall,
        schema: ToolSchema | None = None,
        result: ToolResult | None = None,
        approval_needed: bool = False,
    ):
        self.tool_call = tool_call
        self.schema = schema
        self.result = result
        self.approval_needed = approval_needed


# Type alias for the approval callback
ApprovalCallback = Callable[[ToolCall, ToolSchema | None], Awaitable[bool]]


class AgentLoop:
    """The core agent loop. Receives input, uses tools, delivers results.

    The loop:
    1. Build messages (system prompt + conversation history + user message)
    2. Stream LLM response with tool definitions
    3. If no tool calls -> yield final text, done
    4. For each tool call: check policy -> prompt approval if needed -> execute -> audit
    5. Append tool results, go to step 2
    6. Cap at max_tool_rounds
    """

    def __init__(
        self,
        definition: AgentDefinition,
        llm: LlmClient,
        tool_registry: ToolRegistry,
        approval_callback: ApprovalCallback | None = None,
        audit_log: AuditLog | None = None,
        tool_executor: ToolExecutor | None = None,
        metrics_collector: MetricsCollector | None = None,
        conflict_detector: ConflictDetector | None = None,
        debug_mode: DebugMode | None = None,
        strategy_advisor: Any | None = None,
        prompt_enhancers: list[Any] | None = None,
    ):
        self.definition = definition
        self._llm = llm
        self._tools = tool_registry
        self._approval_callback = approval_callback
        self._audit = audit_log
        self._executor = tool_executor
        self._metrics = metrics_collector
        self._conflicts = conflict_detector or ConflictDetector()
        self._debug = debug_mode
        self._strategy = strategy_advisor
        self._prompt_enhancers = prompt_enhancers or []

    async def run(
        self, user_message: str, conversation: Conversation
    ) -> AsyncIterator[StreamEvent | ToolCallEvent]:  # type: ignore[return]
        """Execute one turn: user message -> tool loop -> streamed response."""
        system_prompt = self.definition.system_prompt or DEFAULT_SYSTEM_PROMPT

        # Inject strategy hints if available
        if self._strategy:
            system_prompt = self._strategy.enhance_prompt(system_prompt)

        # Apply prompt enhancers (personality, user context, curiosity, etc.)
        for enhancer in self._prompt_enhancers:
            if hasattr(enhancer, "enhance_prompt"):
                system_prompt = enhancer.enhance_prompt(system_prompt)
            elif callable(enhancer):
                system_prompt = enhancer(system_prompt, conversation)

        correlation_id = uuid.uuid4().hex[:12]

        conversation.add_user(user_message)
        messages = await conversation.build_messages(system_prompt)

        tool_defs = self._build_tool_definitions()

        if self._debug:
            self._debug.log_llm_request(len(messages), len(tool_defs))

        for round_num in range(self.definition.max_tool_rounds):
            # Stream LLM response
            content_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            finish_reason: str | None = None
            llm_start = time.monotonic()

            async for event in self._llm.stream(messages, tool_defs):
                if event.text_delta:
                    content_parts.append(event.text_delta)
                    yield event
                if event.tool_call:
                    tool_calls.append(event.tool_call)
                if event.done:
                    finish_reason = event.finish_reason

            if self._debug:
                self._debug.log_llm_response(
                    sum(len(p) for p in content_parts),
                    len(tool_calls),
                    time.monotonic() - llm_start,
                )

            content = "".join(content_parts) or None

            # No tool calls — we're done
            if not tool_calls or finish_reason != "tool_use":
                conversation.add_assistant(content)
                return

            # Add assistant message with tool calls to context
            messages.append(
                Message(role="assistant", content=content, tool_calls=tool_calls)
            )

            # Execute each tool call
            for tc in tool_calls:
                tool = self._tools.get(tc.name)
                schema = tool.schema if tool else None

                # Policy check
                needs_approval = self._needs_approval(schema)

                # Yield "starting" event
                yield ToolCallEvent(
                    tool_call=tc, schema=schema, approval_needed=needs_approval
                )

                # Get approval if needed
                if needs_approval:
                    if self._approval_callback:
                        approved = await self._approval_callback(tc, schema)
                        if not approved:
                            result = ToolResult.fail("Denied by user.")
                            yield ToolCallEvent(tool_call=tc, schema=schema, result=result)
                            messages.append(
                                Message(
                                    role="tool",
                                    content=self._serialize_result(result),
                                    tool_call_id=tc.id,
                                )
                            )
                            continue
                    else:
                        result = ToolResult.fail(
                            "This action requires approval but no approval handler is configured."
                        )
                        yield ToolCallEvent(tool_call=tc, schema=schema, result=result)
                        messages.append(
                            Message(
                                role="tool",
                                content=self._serialize_result(result),
                                tool_call_id=tc.id,
                            )
                        )
                        continue

                # Conflict detection
                conflict = self._conflicts.check(tc.name, tc.arguments)
                if conflict and conflict.severity == "error":
                    result = ToolResult.fail(f"Conflict: {conflict.message}")
                    yield ToolCallEvent(tool_call=tc, schema=schema, result=result)
                    messages.append(
                        Message(
                            role="tool",
                            content=self._serialize_result(result),
                            tool_call_id=tc.id,
                        )
                    )
                    continue

                # Execute
                tool_start = time.monotonic()

                if tool is None:
                    result = ToolResult.fail(f"Unknown tool: {tc.name}")
                else:
                    ctx = ToolContext(
                        workspace_root=self.definition.workspace_root or ".",
                        correlation_id=correlation_id,
                        agent_id=self.definition.agent_id,
                        dry_run=self.definition.dry_run,
                    )

                    if self._debug:
                        self._debug.log_tool_call(tc.name, tc.arguments)

                    try:
                        if self._executor:
                            result = await self._executor.run(tool, tc.arguments, ctx)
                        else:
                            result = await tool.execute(tc.arguments, ctx)
                    except Exception as e:
                        result = ToolResult.fail(f"Tool execution error: {e}")

                tool_duration = time.monotonic() - tool_start

                if self._debug:
                    self._debug.log_tool_result(
                        tc.name,
                        not result.is_error,
                        len(result.output or result.error or ""),
                    )

                # Record conflict tracking
                if not result.is_error:
                    self._conflicts.record(tc.name, tc.arguments)

                # Yield "completed" event with the result
                yield ToolCallEvent(tool_call=tc, schema=schema, result=result)
                messages.append(
                    Message(
                        role="tool",
                        content=self._serialize_result(result),
                        tool_call_id=tc.id,
                    )
                )

                # Metrics
                if self._metrics:
                    self._metrics.record(
                        ToolMetric(
                            tool_name=tc.name,
                            agent_id=self.definition.agent_id,
                            success=not result.is_error,
                            duration_s=tool_duration,
                            error_type=(
                                result.error_type.name if result.error_type else None
                            ),
                        )
                    )

                # Audit log
                if self._audit:
                    await self._audit.log_tool_call(
                        tool_call=tc,
                        result=result,
                        agent_id=self.definition.agent_id,
                        correlation_id=correlation_id,
                        risk_tier=schema.risk_tier if schema else None,
                    )

        # Max rounds exceeded
        conversation.add_assistant("Reached maximum tool rounds.")
        yield StreamEvent(text_delta="\n[Reached maximum tool rounds]", done=True)

    def _build_tool_definitions(self) -> list[ToolDefinition]:
        """Build LLM tool definitions filtered by agent's allow/deny lists."""
        schemas = self._tools.filter(
            allow=self.definition.tool_allow or None,
            deny=self.definition.tool_deny or None,
        )
        return [
            ToolDefinition(
                name=s.name,
                description=s.description,
                parameters=s.parameters,
            )
            for s in schemas
        ]

    def _needs_approval(self, schema: ToolSchema | None) -> bool:
        """Check if a tool call requires user approval based on autonomy level."""
        if schema is None:
            return True

        level = self.definition.autonomy_level

        if level >= 3:
            return False
        if level == 2:
            return schema.risk_tier >= RiskTier.DESTRUCTIVE
        if level == 1:
            return schema.risk_tier >= RiskTier.WRITE_EXTERNAL
        return True

    def _serialize_result(self, result: ToolResult) -> str:
        """Serialize a tool result for the LLM context."""
        if result.is_error:
            return json.dumps({"error": result.error})
        return result.output or "OK"
