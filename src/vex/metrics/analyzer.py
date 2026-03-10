"""Metrics analyzer — identifies patterns and suggests strategies."""

from __future__ import annotations

from typing import Any

from .collector import MetricsCollector


class MetricsAnalyzer:
    """Analyzes historical metrics to improve agent behavior."""

    def __init__(self, collector: MetricsCollector) -> None:
        self._collector = collector

    def suggest_strategy(self, tool_names: list[str] | None = None) -> str | None:
        """Generate strategy hints based on historical performance."""
        hints: list[str] = []

        tools = tool_names or self._get_used_tools()
        for tool in tools:
            reliability = self._collector.get_tool_reliability(tool)
            stats = self._collector.get_tool_stats(tool)

            if stats["total"] < 5:
                continue  # Not enough data

            if reliability < 0.5:
                hints.append(
                    f"Tool '{tool}' has a low success rate ({reliability:.0%}). "
                    f"Consider alternative approaches."
                )
            elif reliability < 0.8:
                hints.append(
                    f"Tool '{tool}' succeeds {reliability:.0%} of the time. "
                    f"Double-check arguments before calling."
                )

            avg_duration = stats.get("avg_duration_s", 0)
            if avg_duration > 10:
                hints.append(
                    f"Tool '{tool}' is slow (avg {avg_duration:.1f}s). "
                    f"Batch operations when possible."
                )

        if not hints:
            return None

        return "\n".join(["## Performance Hints"] + [f"- {h}" for h in hints])

    def get_summary(self) -> dict[str, Any]:
        """Get an overall performance summary."""
        all_stats = self._collector.get_tool_stats()
        errors = self._collector.get_common_errors(5)

        return {
            "overall": all_stats,
            "top_errors": errors,
            "tool_reliability": {
                tool: self._collector.get_tool_reliability(tool)
                for tool in self._get_used_tools()
            },
        }

    def _get_used_tools(self) -> list[str]:
        """Get list of tools that have been used."""
        metrics = self._collector._load_all()
        return list({m["tool_name"] for m in metrics if "tool_name" in m})
