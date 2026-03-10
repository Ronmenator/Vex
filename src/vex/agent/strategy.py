"""Strategy advisor — injects performance-based hints into system prompts."""

from __future__ import annotations

from typing import Any

from vex.metrics.analyzer import MetricsAnalyzer


class StrategyAdvisor:
    """Consults metrics and injects strategy hints into system prompts."""

    def __init__(self, analyzer: MetricsAnalyzer) -> None:
        self._analyzer = analyzer

    def enhance_prompt(self, base_prompt: str) -> str:
        """Add performance-based strategy hints to a system prompt."""
        hints = self._analyzer.suggest_strategy()
        if hints:
            return f"{base_prompt}\n\n{hints}"
        return base_prompt
