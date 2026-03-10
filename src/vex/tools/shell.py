"""Tool: execute shell commands."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from vex.security.sanitizer import redact_secrets
from .base import RiskTier, ToolContext, ToolResult, ToolSchema

# Commands that could expose secrets — blocked outright
_BLOCKED_COMMAND_PATTERNS = [
    re.compile(r"\b(?:printenv|env\b)(?:\s|$)", re.IGNORECASE),
    re.compile(r"\bcat\s+.*\.env\b", re.IGNORECASE),
    re.compile(r"\btype\s+.*\.env\b", re.IGNORECASE),  # Windows equivalent
    re.compile(r"\becho\s+.*\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)\w*\}?", re.IGNORECASE),
    re.compile(r"\bset\b\s*$"),  # bare 'set' on Windows dumps env vars
]


class ShellTool:
    """Execute shell commands within the workspace."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="shell",
            description="Execute a shell command in the workspace. Returns stdout, stderr, and exit code.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory relative to workspace (default: workspace root)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 60)",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
            risk_tier=RiskTier.DESTRUCTIVE,
            group="runtime",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        command = arguments["command"]
        cwd = arguments.get("cwd")
        timeout = arguments.get("timeout", 60)

        # Block commands designed to extract secrets
        for pattern in _BLOCKED_COMMAND_PATTERNS:
            if pattern.search(command):
                return ToolResult.fail(
                    "Blocked: this command could expose environment secrets."
                )

        work_dir = Path(context.workspace_root)
        if cwd:
            work_dir = work_dir / cwd

        try:
            work_dir = work_dir.resolve()
        except (OSError, ValueError):
            return ToolResult.fail(f"Invalid working directory: {cwd}")

        workspace = Path(context.workspace_root).resolve()
        if not str(work_dir).startswith(str(workspace)):
            return ToolResult.fail("Working directory must be within workspace.")

        # Select shell based on platform
        if sys.platform == "win32":
            shell_cmd = ["cmd.exe", "/c", command]
        else:
            shell_cmd = ["/bin/sh", "-c", command]

        try:
            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                cwd=str(work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult.fail(f"Command timed out after {timeout}s")

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Truncate large outputs
            max_len = 50_000
            if len(stdout) > max_len:
                stdout = stdout[:max_len] + "\n... (truncated)"
            if len(stderr) > max_len:
                stderr = stderr[:max_len] + "\n... (truncated)"

            result = {
                "stdout": redact_secrets(stdout),
                "stderr": redact_secrets(stderr),
                "exit_code": process.returncode,
            }

            return ToolResult.ok(json.dumps(result))
        except OSError as e:
            return ToolResult.fail(f"Failed to execute command: {e}")
