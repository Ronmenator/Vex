"""Plugin loader — discovers and loads tool plugins via entry points."""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import Any

from vex.tools.base import Tool
from vex.tools.registry import ToolRegistry


ENTRY_POINT_GROUP = "vex.tools"


class PluginLoader:
    """Discovers and loads tool plugins from installed packages."""

    def __init__(self) -> None:
        self._loaded: dict[str, Tool] = {}
        self._errors: list[str] = []

    def discover(self) -> list[Tool]:
        """Discover all installed plugins via entry points."""
        tools: list[Tool] = []

        try:
            eps = importlib.metadata.entry_points()
            # Python 3.12+ returns a SelectableGroups or dict
            if hasattr(eps, "select"):
                plugin_eps = eps.select(group=ENTRY_POINT_GROUP)
            elif isinstance(eps, dict):
                plugin_eps = eps.get(ENTRY_POINT_GROUP, [])
            else:
                plugin_eps = [ep for ep in eps if ep.group == ENTRY_POINT_GROUP]
        except Exception:
            return tools

        for ep in plugin_eps:
            try:
                tool_class = ep.load()
                tool = tool_class()

                # Validate it implements the Tool protocol
                if not hasattr(tool, "schema") or not hasattr(tool, "execute"):
                    self._errors.append(
                        f"Plugin '{ep.name}' does not implement the Tool protocol."
                    )
                    continue

                self._loaded[ep.name] = tool
                tools.append(tool)
            except Exception as e:
                self._errors.append(f"Failed to load plugin '{ep.name}': {e}")

        return tools

    def register_all(self, registry: ToolRegistry) -> int:
        """Discover and register all plugins. Returns count registered."""
        tools = self.discover()
        for tool in tools:
            registry.register(tool)
        return len(tools)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def loaded_plugins(self) -> dict[str, Tool]:
        return dict(self._loaded)
