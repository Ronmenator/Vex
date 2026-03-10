"""Meta-tool: delegate a task to a sub-agent."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


# Type for the delegation callback
DelegateFunc = Callable[[str, str], Awaitable[str]]


class AgentDelegateTool:
    """Delegate a task to another agent and receive its response."""

    def __init__(self, delegate_func: DelegateFunc) -> None:
        self._delegate = delegate_func

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="agent.delegate",
            description=(
                "Delegate a task to another registered agent. The agent runs independently "
                "and returns its response. Use this after creating a specialist agent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the target agent to delegate to",
                    },
                    "task": {
                        "type": "string",
                        "description": "Task description / prompt for the agent",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context to provide to the agent",
                    },
                },
                "required": ["agent_id", "task"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="agents",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        agent_id = arguments["agent_id"]
        task = arguments["task"]
        extra_context = arguments.get("context", "")

        full_prompt = task
        if extra_context:
            full_prompt += f"\n\nAdditional context: {extra_context}"

        try:
            response = await self._delegate(agent_id, full_prompt)
            return ToolResult.ok(response)
        except Exception as e:
            return ToolResult.fail(f"Delegation failed: {e}")
