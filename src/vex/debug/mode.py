"""Debug mode — verbose logging of LLM requests, tool calls, and timing."""

from __future__ import annotations

import json
import time
from typing import Any

from rich.console import Console
from rich.text import Text


class DebugMode:
    """When enabled, logs detailed debug information."""

    def __init__(self, console: Console | None = None) -> None:
        self._enabled = False
        self._console = console or Console(stderr=True)
        self._events: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def toggle(self) -> bool:
        """Toggle debug mode. Returns new state."""
        self._enabled = not self._enabled
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def log_llm_request(
        self, message_count: int, tool_count: int, model: str = ""
    ) -> None:
        """Log an outgoing LLM request."""
        if not self._enabled:
            return
        self._print_debug(
            f"LLM request: {message_count} messages, {tool_count} tools"
            + (f", model={model}" if model else "")
        )

    def log_llm_response(
        self, content_length: int, tool_calls: int, duration_s: float
    ) -> None:
        """Log an LLM response."""
        if not self._enabled:
            return
        self._print_debug(
            f"LLM response: {content_length} chars, "
            f"{tool_calls} tool calls, {duration_s:.2f}s"
        )

    def log_tool_call(
        self, tool_name: str, arguments: dict[str, Any], duration_s: float = 0
    ) -> None:
        """Log a tool execution."""
        if not self._enabled:
            return

        args_str = json.dumps(arguments, default=str)
        if len(args_str) > 200:
            args_str = args_str[:200] + "..."

        msg = f"Tool: {tool_name}({args_str})"
        if duration_s > 0:
            msg += f" [{duration_s:.3f}s]"
        self._print_debug(msg)

    def log_tool_result(
        self, tool_name: str, success: bool, output_length: int
    ) -> None:
        """Log a tool result."""
        if not self._enabled:
            return
        status = "OK" if success else "ERROR"
        self._print_debug(f"Result: {tool_name} → {status} ({output_length} chars)")

    def log_event(self, event_type: str, details: str) -> None:
        """Log a generic debug event."""
        if not self._enabled:
            return
        self._print_debug(f"{event_type}: {details}")

    def _print_debug(self, message: str) -> None:
        text = Text()
        text.append("  [debug] ", style="dim cyan")
        text.append(message, style="dim")
        self._console.print(text)

        self._events.append({"time": time.monotonic(), "message": message})

    def get_events(self) -> list[dict[str, Any]]:
        """Get all logged debug events."""
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()
