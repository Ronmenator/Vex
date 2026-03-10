"""Tool: read file contents."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from vex.security.sanitizer import redact_secrets
from .base import RiskTier, ToolContext, ToolResult, ToolSchema

# Files whose contents should be redacted before showing to the agent
_SENSITIVE_FILENAMES = {".env", ".env.local", ".env.production", ".env.development"}
_SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


class FileReadTool:
    """Read the contents of a file within the workspace."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_read",
            description="Read the contents of a file. Returns the file text with line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (1-based)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of lines to read",
                    },
                },
                "required": ["path"],
            },
            risk_tier=RiskTier.READ_ONLY,
            group="fs",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        rel_path = arguments["path"]
        offset = arguments.get("offset", 1)
        limit = arguments.get("limit")

        full_path = Path(context.workspace_root) / rel_path
        try:
            full_path = full_path.resolve()
        except (OSError, ValueError):
            return ToolResult.fail(f"Invalid path: {rel_path}")

        # Sandbox check
        workspace = Path(context.workspace_root).resolve()
        if not str(full_path).startswith(str(workspace)):
            return ToolResult.fail("Path traversal denied.")

        if not full_path.is_file():
            return ToolResult.fail(f"File not found: {rel_path}")

        try:
            text = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ToolResult.fail(f"Cannot read file: {e}")

        lines = text.splitlines()
        start = max(0, offset - 1)
        end = start + limit if limit else len(lines)
        selected = lines[start:end]

        # Format with line numbers
        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            numbered.append(f"{i:>6}\t{line}")

        result = "\n".join(numbered)
        if len(result) > 100_000:
            result = result[:100_000] + "\n... (truncated)"

        # Redact secrets from sensitive files (and run general redaction on all files)
        fname = full_path.name.lower()
        if fname in _SENSITIVE_FILENAMES or full_path.suffix.lower() in _SENSITIVE_SUFFIXES:
            return ToolResult.ok(
                f"[Security] {rel_path} contains sensitive data. "
                "Secret values have been redacted.\n\n" + redact_secrets(result)
            )

        return ToolResult.ok(redact_secrets(result))
