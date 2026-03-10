"""Tool: search file contents by regex pattern."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class GrepTool:
    """Search for a regex pattern in file contents within the workspace."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="grep",
            description="Search file contents for a regex pattern. Returns matching lines with file paths and line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search in (relative to workspace)",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File glob filter (e.g. '*.py', '*.ts')",
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "Case-insensitive search",
                    },
                },
                "required": ["pattern"],
            },
            risk_tier=RiskTier.READ_ONLY,
            group="fs",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        pattern_str = arguments["pattern"]
        sub_path = arguments.get("path", "")
        file_glob = arguments.get("glob", "**/*")
        case_insensitive = arguments.get("case_insensitive", False)

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

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern_str, flags)
        except re.error as e:
            return ToolResult.fail(f"Invalid regex: {e}")

        matches: list[str] = []
        max_matches = 200

        # If search_root is a file, search just that file
        if search_root.is_file():
            files = [search_root]
        else:
            files = sorted(search_root.glob(file_glob))

        for file_path in files:
            if not file_path.is_file():
                continue
            # Skip binary files
            if _is_binary(file_path):
                continue

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            rel = str(file_path.relative_to(workspace)).replace("\\", "/")

            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(matches) >= max_matches:
                        matches.append(f"... (capped at {max_matches} matches)")
                        return ToolResult.ok("\n".join(matches))

        if not matches:
            return ToolResult.ok("No matches found.")

        return ToolResult.ok("\n".join(matches))


def _is_binary(path: Path) -> bool:
    """Quick check if a file is likely binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except OSError:
        return True
