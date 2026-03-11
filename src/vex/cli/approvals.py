"""Approval management for the CLI."""

from __future__ import annotations

from typing import Any

from vex.cli.renderer import Renderer
from vex.agent.loop import ToolCallEvent
from vex.llm.base import ToolCall
from vex.tools.base import ToolSchema


class ApprovalManager:
    """Manages tool approval state for the CLI session."""

    def __init__(self, renderer: Renderer, session: Any = None) -> None:
        self._renderer = renderer
        self._session = session
        self._always_approved: set[str] = set()  # Tool names approved for the session

    async def check_approval(
        self, tool_call: ToolCall, schema: ToolSchema | None
    ) -> bool:
        """Prompt the user for approval. Returns True if approved."""
        tool_name = tool_call.name

        # Check if already approved for this session
        if tool_name in self._always_approved:
            return True

        event = ToolCallEvent(tool_call=tool_call, schema=schema, approval_needed=True)
        response = await self._renderer.render_approval_prompt(event, session=self._session)

        if response in ("y", "yes"):
            return True
        if response in ("a", "always"):
            self._always_approved.add(tool_name)
            return True
        return False

    def reset(self) -> None:
        """Reset all session-level approvals."""
        self._always_approved.clear()
