"""Conflict detection — warns about concurrent or conflicting operations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConflictWarning:
    """A detected conflict between operations."""

    message: str
    severity: str  # "info", "warning", "error"
    conflicting_tool: str | None = None


class ConflictDetector:
    """Tracks file operations and detects conflicts."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        # Tracks recent operations: {path: (tool_name, timestamp, operation)}
        self._recent_ops: dict[str, list[tuple[str, float, str]]] = {}

    def check(self, tool_name: str, arguments: dict[str, Any]) -> ConflictWarning | None:
        """Check for conflicts before executing a tool."""
        self._prune_expired()

        path = self._extract_path(tool_name, arguments)
        if not path:
            return None

        ops = self._recent_ops.get(path, [])

        # Check for write-after-write conflict
        for prev_tool, ts, prev_op in ops:
            if prev_op == "write" and self._is_write(tool_name):
                return ConflictWarning(
                    message=f"File '{path}' was recently modified by {prev_tool}. "
                    f"Writing again may cause data loss.",
                    severity="warning",
                    conflicting_tool=prev_tool,
                )

        return None

    def record(self, tool_name: str, arguments: dict[str, Any]) -> None:
        """Record a completed operation."""
        path = self._extract_path(tool_name, arguments)
        if not path:
            return

        op = "write" if self._is_write(tool_name) else "read"
        self._recent_ops.setdefault(path, []).append((tool_name, time.monotonic(), op))

    def _extract_path(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        """Extract the file path from tool arguments."""
        if tool_name in ("file_read", "file_write", "file_edit"):
            return arguments.get("path")
        if tool_name == "shell":
            return None  # Can't reliably extract paths from shell commands
        return None

    def _is_write(self, tool_name: str) -> bool:
        return tool_name in ("file_write", "file_edit")

    def _prune_expired(self) -> None:
        """Remove entries older than TTL."""
        now = time.monotonic()
        for path in list(self._recent_ops.keys()):
            self._recent_ops[path] = [
                (t, ts, op) for t, ts, op in self._recent_ops[path] if now - ts < self._ttl
            ]
            if not self._recent_ops[path]:
                del self._recent_ops[path]
