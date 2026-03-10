"""Append-only JSONL audit log."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vex.llm.base import ToolCall
from vex.tools.base import ToolResult


# Patterns to redact from audit entries
_SECRET_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE),  # OpenAI keys
    re.compile(r"(sk-ant-[a-zA-Z0-9-]{20,})", re.IGNORECASE),  # Anthropic keys
    re.compile(r"(ghp_[a-zA-Z0-9]{36})", re.IGNORECASE),  # GitHub PATs
    re.compile(r"(password\s*[:=]\s*\S+)", re.IGNORECASE),
    re.compile(r"(token\s*[:=]\s*\S+)", re.IGNORECASE),
]


@dataclass
class AuditEntry:
    """A single audit log entry."""

    timestamp: str
    event_type: str  # "tool_call" | "tool_result" | "approval" | "agent_created" | "error"
    agent_id: str
    correlation_id: str
    tool_name: str | None = None
    arguments_summary: str | None = None
    result_summary: str | None = None
    risk_tier: int | None = None
    error: str | None = None


class AuditLog:
    """Append-only JSONL audit log with secret redaction.

    Creates one file per day in the configured directory.
    """

    def __init__(self, directory: str, enabled: bool = True) -> None:
        self._directory = Path(directory)
        self._enabled = enabled
        if self._enabled:
            self._directory.mkdir(parents=True, exist_ok=True)

    async def log_tool_call(
        self,
        tool_call: ToolCall,
        result: ToolResult,
        agent_id: str,
        correlation_id: str,
        risk_tier: int | None = None,
    ) -> None:
        """Log a tool call and its result."""
        if not self._enabled:
            return

        # Redact arguments
        args_summary = _redact(_truncate(json.dumps(tool_call.arguments), 500))
        result_summary = _redact(
            _truncate(result.output or result.error or "", 500)
        )

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="tool_call",
            agent_id=agent_id,
            correlation_id=correlation_id,
            tool_name=tool_call.name,
            arguments_summary=args_summary,
            result_summary=result_summary,
            risk_tier=risk_tier,
            error=result.error if result.is_error else None,
        )
        self._append(entry)

    async def log_event(
        self,
        event_type: str,
        agent_id: str,
        correlation_id: str,
        **kwargs: Any,
    ) -> None:
        """Log a generic event."""
        if not self._enabled:
            return

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            agent_id=agent_id,
            correlation_id=correlation_id,
            **kwargs,
        )
        self._append(entry)

    def _append(self, entry: AuditEntry) -> None:
        """Append an entry to today's log file."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self._directory / f"{today}.jsonl"

        line = json.dumps(asdict(entry), default=str) + "\n"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)

    def query_recent(self, limit: int = 50) -> list[AuditEntry]:
        """Query the most recent audit entries."""
        entries: list[AuditEntry] = []

        # Read from most recent files
        log_files = sorted(self._directory.glob("*.jsonl"), reverse=True)
        for log_file in log_files:
            try:
                for line in reversed(log_file.read_text(encoding="utf-8").splitlines()):
                    if line.strip():
                        data = json.loads(line)
                        entries.append(AuditEntry(**data))
                        if len(entries) >= limit:
                            return entries
            except (json.JSONDecodeError, OSError):
                continue

        return entries


def _redact(text: str) -> str:
    """Redact known secret patterns from text."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
