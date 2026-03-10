"""Summarizer — condenses tool execution traces for the user."""

from __future__ import annotations

from typing import Any


class Summarizer:
    """Generates human-readable summaries of tool execution traces."""

    def summarize_tool_chain(self, events: list[dict[str, Any]]) -> str:
        """Summarize a chain of tool executions."""
        if not events:
            return "No operations performed."

        successes = sum(1 for e in events if e.get("success", False))
        failures = len(events) - successes
        tools_used = list(dict.fromkeys(e.get("tool", "unknown") for e in events))

        parts = [f"Executed {len(events)} operation(s)"]

        if len(tools_used) <= 5:
            parts.append(f"using: {', '.join(tools_used)}")

        if failures > 0:
            parts.append(f"({successes} succeeded, {failures} failed)")
        else:
            parts.append("(all succeeded)")

        return " ".join(parts) + "."

    def summarize_long_output(self, output: str, max_lines: int = 20) -> str:
        """Summarize a long tool output."""
        lines = output.splitlines()
        if len(lines) <= max_lines:
            return output

        head = lines[:max_lines // 2]
        tail = lines[-(max_lines // 2):]
        omitted = len(lines) - max_lines

        return "\n".join(head + [f"\n... ({omitted} lines omitted) ...\n"] + tail)
