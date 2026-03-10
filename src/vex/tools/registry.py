"""Tool registry — stores and retrieves tools by name."""

from __future__ import annotations

from .base import Tool, ToolSchema


class ToolRegistry:
    """Registry of available tools with group-based filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Overwrites if name already exists."""
        self._tools[tool.schema.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_all(self) -> list[ToolSchema]:
        """List schemas of all registered tools."""
        return [t.schema for t in self._tools.values()]

    def list_names(self) -> list[str]:
        """List names of all registered tools."""
        return list(self._tools.keys())

    def filter(
        self,
        allow: list[str] | None = None,
        deny: list[str] | None = None,
    ) -> list[ToolSchema]:
        """List tools filtered by allow/deny lists.

        Allow/deny entries can match tool names or group names.
        Empty allow list means all allowed. Deny takes precedence.
        """
        result = []
        for tool in self._tools.values():
            s = tool.schema
            # Deny check
            if deny:
                if s.name in deny or s.group in deny:
                    continue
            # Allow check (empty = all allowed)
            if allow:
                if s.name not in allow and s.group not in allow:
                    continue
            result.append(s)
        return result

    def discover_plugins(self) -> int:
        """Discover and register tool plugins. Returns count loaded."""
        try:
            from vex.plugins.loader import PluginLoader

            loader = PluginLoader()
            return loader.register_all(self)
        except ImportError:
            return 0
