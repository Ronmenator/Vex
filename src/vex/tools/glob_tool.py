"""Tool: find files by glob pattern."""

from __future__ import annotations

import glob as globlib
from pathlib import Path
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class GlobTool:
    """Search for files matching a glob pattern within the workspace."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="glob",
            description="Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). Returns matching file paths.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match files against",
                    },
                    "path": {
                        "type": "string",
                        "description": "Subdirectory to search in (relative to workspace)",
                    },
                },
                "required": ["pattern"],
            },
            risk_tier=RiskTier.READ_ONLY,
            group="fs",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        pattern = arguments["pattern"]
        sub_path = arguments.get("path", "")

        search_root = Path(context.workspace_root)
        if sub_path:
            search_root = search_root / sub_path

        try:
            search_root = search_root.resolve()
        except (OSError, ValueError):
            return ToolResult.fail(f"Invalid path: {sub_path}")

        workspace = Path(context.workspace_root).resolve()
        if not str(search_root).startswith(str(workspace)):
            return ToolResult.fail("Path traversal denied.")

        matches = sorted(globlib.glob(str(search_root / pattern), recursive=True))

        # Make paths relative to workspace
        rel_matches = []
        for m in matches:
            try:
                rel = str(Path(m).relative_to(workspace))
                rel_matches.append(rel.replace("\\", "/"))
            except ValueError:
                continue

        if not rel_matches:
            return ToolResult.ok("No files matched the pattern.")

        # Cap output
        if len(rel_matches) > 500:
            result = "\n".join(rel_matches[:500])
            result += f"\n... and {len(rel_matches) - 500} more files"
        else:
            result = "\n".join(rel_matches)

        return ToolResult.ok(result)
