"""Tool protocol, schema, result types, and context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Protocol, runtime_checkable


class RiskTier(IntEnum):
    """Risk classification for tools. Higher = more dangerous."""

    READ_ONLY = 0  # file_read, glob, grep
    WRITE_LOCAL = 1  # file_write, file_edit, agent.create
    WRITE_EXTERNAL = 2  # web_fetch, agent.delegate
    DESTRUCTIVE = 3  # shell (arbitrary commands)


class ToolError(IntEnum):
    """Classification of tool execution errors."""

    TRANSIENT = 0  # Retryable: network hiccup, temporary lock
    TIMEOUT = 1  # Execution exceeded time limit
    RESOURCE_LIMIT = 2  # Memory, CPU, or output size exceeded
    PERMISSION = 3  # Access denied, sandbox violation
    PERMANENT = 4  # Non-retryable: bad arguments, file not found


@dataclass(frozen=True)
class ToolSchema:
    """Declarative schema for a tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object
    risk_tier: RiskTier = RiskTier.READ_ONLY
    group: str = "general"
    timeout: int = 60
    max_retries: int = 0


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool execution."""

    output: str | None = None
    error: str | None = None
    is_error: bool = False
    error_type: ToolError | None = None
    metadata: dict[str, Any] | None = None

    @staticmethod
    def ok(output: str, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output=output, metadata=metadata)

    @staticmethod
    def fail(
        error: str, error_type: ToolError = ToolError.PERMANENT
    ) -> ToolResult:
        return ToolResult(error=error, is_error=True, error_type=error_type)


@dataclass
class ToolContext:
    """Context passed to tool execution."""

    workspace_root: str
    correlation_id: str
    agent_id: str
    dry_run: bool = False


@runtime_checkable
class Tool(Protocol):
    """Protocol that all tools must implement."""

    @property
    def schema(self) -> ToolSchema: ...

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...
