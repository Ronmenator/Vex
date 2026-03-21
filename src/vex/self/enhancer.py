"""Self-improvement prompt enhancer — injects active self-learned rules into the system prompt."""

from __future__ import annotations

from itertools import groupby

from .rules import RuleStore


class SelfImprovementEnhancer:
    """Prompt enhancer that appends active self-learned rules.

    Rules are grouped by category and sorted by confidence so the agent
    sees its strongest learnings first.
    """

    def __init__(self, rule_store: RuleStore) -> None:
        self._store = rule_store

    def enhance_prompt(self, system_prompt: str) -> str:
        rules = self._store.get_active_rules()
        if not rules:
            return system_prompt

        lines = [
            "\n\n## Self-Learned Rules",
            "These are behavioral rules you discovered through reflection on your own "
            "activity outcomes. Follow them when relevant — they represent what you've "
            "learned works well. Use the `self_improve` tool to evaluate, update, or "
            "retire rules as you gather new evidence.",
        ]

        # Group by category
        for category, group in groupby(rules, key=lambda r: r.category):
            lines.append(f"\n### {category.title()}")
            for rule in group:
                conf = f"{rule.confidence:.0%}"
                lines.append(f"- [{conf}] {rule.hypothesis}")
                if rule.evidence:
                    lines.append(f"  _Evidence: {rule.evidence}_")

        return system_prompt + "\n".join(lines)
