"""Tool: file diff/comparison."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class FileDiffTool:
    """Compare two files or a file against provided content."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_diff",
            description=(
                "Compare two files or a file against provided content. "
                "Returns a unified diff. Use path_a + path_b to compare two files, "
                "or path + content to compare a file against new content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path (for file vs content comparison)",
                    },
                    "path_a": {
                        "type": "string",
                        "description": "First file path (for file vs file comparison)",
                    },
                    "path_b": {
                        "type": "string",
                        "description": "Second file path (for file vs file comparison)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to compare against (for file vs content)",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Number of context lines in diff (default: 3)",
                        "default": 3,
                    },
                },
            },
            risk_tier=RiskTier.READ_ONLY,
            group="fs",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        workspace = Path(context.workspace_root).resolve()
        context_lines = arguments.get("context_lines", 3)

        path_a = arguments.get("path_a")
        path_b = arguments.get("path_b")
        path = arguments.get("path")
        content = arguments.get("content")

        if path_a and path_b:
            # File vs file
            a_path = (workspace / path_a).resolve()
            b_path = (workspace / path_b).resolve()

            if not str(a_path).startswith(str(workspace)):
                return ToolResult.fail(f"Path traversal denied: {path_a}")
            if not str(b_path).startswith(str(workspace)):
                return ToolResult.fail(f"Path traversal denied: {path_b}")

            if not a_path.is_file():
                return ToolResult.fail(f"File not found: {path_a}")
            if not b_path.is_file():
                return ToolResult.fail(f"File not found: {path_b}")

            a_lines = a_path.read_text(encoding="utf-8").splitlines(keepends=True)
            b_lines = b_path.read_text(encoding="utf-8").splitlines(keepends=True)
            label_a, label_b = path_a, path_b

        elif path and content is not None:
            # File vs content
            file_path = (workspace / path).resolve()
            if not str(file_path).startswith(str(workspace)):
                return ToolResult.fail(f"Path traversal denied: {path}")
            if not file_path.is_file():
                return ToolResult.fail(f"File not found: {path}")

            a_lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
            b_lines = content.splitlines(keepends=True)
            label_a, label_b = f"{path} (current)", f"{path} (proposed)"

        else:
            return ToolResult.fail(
                "Provide either (path_a + path_b) or (path + content)."
            )

        diff = list(
            difflib.unified_diff(a_lines, b_lines, fromfile=label_a, tofile=label_b, n=context_lines)
        )

        if not diff:
            return ToolResult.ok("Files are identical.")

        return ToolResult.ok("".join(diff))
