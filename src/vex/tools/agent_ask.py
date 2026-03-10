"""Meta-tool: ask the user a question."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from .base import RiskTier, ToolContext, ToolResult, ToolSchema

# Type for the ask callback
AskFunc = Callable[[str], Awaitable[str]]


class AgentAskTool:
    """Ask the user a clarifying question and receive their response."""

    def __init__(self, ask_func: AskFunc) -> None:
        self._ask = ask_func

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="agent.ask",
            description=(
                "Ask the user a clarifying question. Use this when you need more information "
                "to proceed, or when you want to confirm a destructive action."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                },
                "required": ["question"],
            },
            risk_tier=RiskTier.READ_ONLY,
            group="agents",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        question = arguments["question"]

        try:
            answer = await self._ask(question)
            return ToolResult.ok(answer)
        except Exception as e:
            return ToolResult.fail(f"Failed to get user response: {e}")
