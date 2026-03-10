"""Tool: batch file operations with atomic rollback."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class FileBatchTool:
    """Execute multiple file operations atomically."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_batch",
            description=(
                "Execute multiple file operations atomically. If any operation fails, "
                "all changes are rolled back. Each operation has an action (write, delete, copy, move) "
                "and relevant parameters."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["write", "delete", "copy", "move"],
                                },
                                "path": {"type": "string"},
                                "content": {"type": "string", "description": "For write action"},
                                "dest": {"type": "string", "description": "For copy/move actions"},
                            },
                            "required": ["action", "path"],
                        },
                        "description": "List of file operations to perform",
                    },
                },
                "required": ["operations"],
            },
            risk_tier=RiskTier.WRITE_LOCAL,
            group="fs",
            timeout=120,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        operations = arguments.get("operations", [])
        if not operations:
            return ToolResult.fail("No operations provided.")

        workspace = Path(context.workspace_root).resolve()
        rollback_actions: list[tuple[str, Path, bytes | None]] = []
        completed = 0

        try:
            for op in operations:
                action = op["action"]
                rel_path = op["path"]
                full_path = (workspace / rel_path).resolve()

                if not str(full_path).startswith(str(workspace)):
                    raise ValueError(f"Path traversal denied: {rel_path}")

                if action == "write":
                    content = op.get("content", "")
                    # Save original for rollback
                    original = full_path.read_bytes() if full_path.is_file() else None
                    rollback_actions.append(("write", full_path, original))
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content, encoding="utf-8")

                elif action == "delete":
                    if full_path.is_file():
                        original = full_path.read_bytes()
                        rollback_actions.append(("delete", full_path, original))
                        full_path.unlink()

                elif action == "copy":
                    dest = op.get("dest")
                    if not dest:
                        raise ValueError("copy requires 'dest'")
                    dest_path = (workspace / dest).resolve()
                    if not str(dest_path).startswith(str(workspace)):
                        raise ValueError(f"Path traversal denied: {dest}")
                    original = dest_path.read_bytes() if dest_path.is_file() else None
                    rollback_actions.append(("write", dest_path, original))
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(full_path, dest_path)

                elif action == "move":
                    dest = op.get("dest")
                    if not dest:
                        raise ValueError("move requires 'dest'")
                    dest_path = (workspace / dest).resolve()
                    if not str(dest_path).startswith(str(workspace)):
                        raise ValueError(f"Path traversal denied: {dest}")
                    original_content = full_path.read_bytes() if full_path.is_file() else None
                    dest_original = dest_path.read_bytes() if dest_path.is_file() else None
                    rollback_actions.append(("delete", full_path, original_content))
                    rollback_actions.append(("write", dest_path, dest_original))
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(full_path), str(dest_path))

                else:
                    raise ValueError(f"Unknown action: {action}")

                completed += 1

            return ToolResult.ok(f"Completed {completed} operation(s) successfully.")

        except Exception as e:
            # Rollback all completed operations
            for action, path, original in reversed(rollback_actions):
                try:
                    if original is not None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(original)
                    elif path.is_file():
                        path.unlink()
                except OSError:
                    pass

            return ToolResult.fail(
                f"Batch failed at operation {completed + 1}: {e}. "
                f"Rolled back {len(rollback_actions)} operation(s)."
            )
