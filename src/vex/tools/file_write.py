"""Tool: write content to a file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class FileWriteTool:
    """Write content to a file in the workspace. Creates directories as needed."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_write",
            description="Write content to a file. Creates parent directories if needed. Set append=true to append instead of overwrite.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write",
                    },
                    "append": {
                        "type": "boolean",
                        "description": "Append instead of overwrite",
                        "default": False,
                    },
                },
                "required": ["path", "content"],
            },
            risk_tier=RiskTier.WRITE_LOCAL,
            group="fs",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        rel_path = arguments["path"]
        content = arguments["content"]
        append = arguments.get("append", False)

        full_path = Path(context.workspace_root) / rel_path
        try:
            full_path = full_path.resolve()
        except (OSError, ValueError):
            return ToolResult.fail(f"Invalid path: {rel_path}")

        # Sandbox check
        workspace = Path(context.workspace_root).resolve()
        if not str(full_path).startswith(str(workspace)):
            return ToolResult.fail("Path traversal denied.")

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Auto-backup before overwrite
            if full_path.is_file() and not append:
                try:
                    from vex.io.backup import BackupManager

                    backup = BackupManager(context.workspace_root)
                    backup.create_backup(full_path, tool_name="file_write")
                except Exception:
                    pass  # Backup failure shouldn't block the write

            if append:
                with open(full_path, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                full_path.write_text(content, encoding="utf-8")

            return ToolResult.ok(f"Written {len(content)} bytes to {rel_path}")
        except OSError as e:
            return ToolResult.fail(f"Write failed: {e}")
