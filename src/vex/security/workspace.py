"""Workspace path sandboxing."""

from __future__ import annotations

from pathlib import Path


class SecurityError(Exception):
    """Raised when a security constraint is violated."""


class WorkspaceSandbox:
    """Validates that file paths stay within the workspace root."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def validate(self, path: str) -> Path:
        """Resolve a relative path and ensure it's within the workspace.

        Returns the resolved absolute path.
        Raises SecurityError on path traversal.
        """
        resolved = (self.root / path).resolve()
        if not self._is_within(resolved):
            raise SecurityError(f"Path traversal denied: {path}")
        return resolved

    def _is_within(self, path: Path) -> bool:
        """Check if a path is within the workspace root."""
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False
