"""Tool: edit a file by exact string replacement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class FileEditTool:
    """Edit a file by replacing exact string matches."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_edit",
            description="Edit a file by replacing an exact string with new text. The old_string must be unique in the file unless replace_all is true.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Exact text to find in the file",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences (default: first only)",
                        "default": False,
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
            risk_tier=RiskTier.WRITE_LOCAL,
            group="fs",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        rel_path = arguments["path"]
        old_string = arguments["old_string"]
        new_string = arguments["new_string"]
        replace_all = arguments.get("replace_all", False)

        if old_string == new_string:
            return ToolResult.fail("old_string and new_string are identical.")

        full_path = Path(context.workspace_root) / rel_path
        try:
            full_path = full_path.resolve()
        except (OSError, ValueError):
            return ToolResult.fail(f"Invalid path: {rel_path}")

        workspace = Path(context.workspace_root).resolve()
        if not str(full_path).startswith(str(workspace)):
            return ToolResult.fail("Path traversal denied.")

        if not full_path.is_file():
            return ToolResult.fail(f"File not found: {rel_path}")

        try:
            content = full_path.read_text(encoding="utf-8")
        except OSError as e:
            return ToolResult.fail(f"Cannot read file: {e}")

        if old_string not in content:
            return ToolResult.fail("old_string not found in file.")

        # Count occurrences
        count = content.count(old_string)

        if not replace_all and count > 1:
            return ToolResult.fail(
                f"old_string is not unique ({count} occurrences). "
                "Use replace_all=true or provide more context."
            )

        # Auto-backup before edit
        try:
            from vex.io.backup import BackupManager

            backup = BackupManager(context.workspace_root)
            backup.create_backup(full_path, tool_name="file_edit")
        except Exception:
            pass  # Backup failure shouldn't block the edit

        # Perform replacement
        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = count
        else:
            idx = content.index(old_string)
            new_content = content[:idx] + new_string + content[idx + len(old_string) :]
            replacements = 1

        try:
            full_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return ToolResult.fail(f"Write failed: {e}")

        return ToolResult.ok(
            f"Edited {rel_path}: {replacements} replacement(s), {len(new_content)} bytes"
        )
