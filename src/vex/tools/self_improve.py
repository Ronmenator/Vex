"""self_improve — Recursive self-improvement tool for Vex.

Allows the agent to propose, evaluate, and retire behavioral rules based on
observed outcomes.  Inspired by the Gödel machine concept of self-referential
improvement with a proof (evidence) gate.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from vex.self.rules import RuleStore, SelfRule
from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


class SelfImproveTool:
    """Tool that lets Vex propose, evaluate, list, retire, and review self-improvement rules."""

    def __init__(self, rule_store: RuleStore) -> None:
        self._store = rule_store

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="self_improve",
            description=(
                "Manage your self-improvement rules — behavioral hypotheses you've "
                "discovered through reflection. Propose new rules when you notice "
                "patterns in what works, evaluate existing rules based on outcomes, "
                "retire rules that no longer apply, or review your recent activity "
                "logs to identify improvement opportunities."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["propose", "list", "evaluate", "retire", "review"],
                        "description": (
                            "propose: create a new behavioral rule from observed evidence; "
                            "list: show all active rules with confidence scores; "
                            "evaluate: update a rule's confidence (up/down) based on new evidence; "
                            "retire: deactivate a rule that's no longer useful; "
                            "review: analyze recent activity logs and suggest improvements"
                        ),
                    },
                    "hypothesis": {
                        "type": "string",
                        "description": "What to do differently (required for propose). "
                        "Max 500 chars. Must not reference security rules or credentials.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Why this works — observed outcome or reasoning (required for propose)",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["engagement", "strategy", "communication", "research", "platform"],
                        "description": "Rule category (required for propose)",
                    },
                    "rule_id": {
                        "type": "string",
                        "description": "Rule ID (required for evaluate and retire)",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Confidence direction (required for evaluate)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why you're evaluating/retiring this rule",
                    },
                    "include_retired": {
                        "type": "boolean",
                        "description": "Include retired rules in list output (default: false)",
                    },
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.WRITE_LOCAL,
            group="meta",
            timeout=30,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments.get("action", "list")

        try:
            if action == "propose":
                return self._propose(arguments)
            elif action == "list":
                return self._list(arguments)
            elif action == "evaluate":
                return self._evaluate(arguments)
            elif action == "retire":
                return self._retire(arguments)
            elif action == "review":
                return await self._review(context)
            else:
                return ToolResult.fail(f"Unknown action: {action}")
        except Exception as e:
            return ToolResult.fail(f"self_improve error: {e}")

    # ── Actions ──────────────────────────────────────────────

    def _propose(self, args: dict[str, Any]) -> ToolResult:
        hypothesis = args.get("hypothesis", "").strip()
        evidence = args.get("evidence", "").strip()
        category = args.get("category", "").strip()

        if not hypothesis:
            return ToolResult.fail("hypothesis is required for propose action")
        if not evidence:
            return ToolResult.fail("evidence is required for propose action")
        if not category:
            return ToolResult.fail("category is required for propose action")

        result = self._store.add_rule(hypothesis, evidence, category)
        if isinstance(result, str):
            return ToolResult.fail(result)

        return ToolResult.ok(
            f"Rule created: [{result.id}]\n"
            f"  Hypothesis: {result.hypothesis}\n"
            f"  Evidence: {result.evidence}\n"
            f"  Category: {result.category}\n"
            f"  Confidence: {result.confidence:.0%}"
        )

    def _list(self, args: dict[str, Any]) -> ToolResult:
        include_retired = args.get("include_retired", False)

        if include_retired:
            rules = self._store.get_all_rules()
        else:
            rules = self._store.get_active_rules()

        if not rules:
            return ToolResult.ok("No rules found. Use 'propose' to create your first self-improvement rule.")

        lines = []
        for r in rules:
            status = "active" if r.active else "retired"
            lines.append(
                f"[{r.id}] ({status}) {r.confidence:.0%} | {r.category}\n"
                f"  {r.hypothesis}\n"
                f"  Evidence: {r.evidence}\n"
                f"  Evaluated {r.evaluation_count}x"
            )

        return ToolResult.ok(f"{len(rules)} rule(s):\n\n" + "\n\n".join(lines))

    def _evaluate(self, args: dict[str, Any]) -> ToolResult:
        rule_id = args.get("rule_id", "").strip()
        direction = args.get("direction", "").strip()
        reason = args.get("reason", "").strip()

        if not rule_id:
            return ToolResult.fail("rule_id is required for evaluate action")
        if not direction:
            return ToolResult.fail("direction ('up' or 'down') is required for evaluate action")

        result = self._store.update_confidence(rule_id, direction, reason)
        if isinstance(result, str):
            return ToolResult.fail(result)

        status = "active" if result.active else "retired (confidence hit zero)"
        return ToolResult.ok(
            f"Rule [{result.id}] evaluated ({direction}):\n"
            f"  Confidence: {result.confidence:.0%} — {status}\n"
            f"  Reason: {reason or '(none)'}"
        )

    def _retire(self, args: dict[str, Any]) -> ToolResult:
        rule_id = args.get("rule_id", "").strip()
        reason = args.get("reason", "").strip()

        if not rule_id:
            return ToolResult.fail("rule_id is required for retire action")

        result = self._store.retire_rule(rule_id, reason)
        if isinstance(result, str):
            return ToolResult.fail(result)

        return ToolResult.ok(
            f"Rule [{result.id}] retired.\n"
            f"  Was: {result.hypothesis}\n"
            f"  Reason: {reason or '(none)'}"
        )

    async def _review(self, context: ToolContext) -> ToolResult:
        """Analyze recent activity logs and summarize outcomes for reflection."""
        log_path = os.path.join(
            context.workspace_root, ".vex", "activity_logs", "activity_runs.jsonl"
        )

        if not os.path.exists(log_path):
            return ToolResult.ok(
                "No activity logs found yet. Run some autonomous activity turns first, "
                "then use 'review' to analyze outcomes."
            )

        # Read last 20 entries
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            return ToolResult.fail(f"Failed to read activity log: {e}")

        entries = []
        for line in lines[-20:]:
            try:
                entries.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

        if not entries:
            return ToolResult.ok("Activity log is empty.")

        # Build summary
        runs = [e for e in entries if e.get("type") != "heartbeat"]
        heartbeats = [e for e in entries if e.get("type") == "heartbeat"]

        total = len(runs)
        ok_count = sum(1 for r in runs if r.get("status") == "ok")
        skip_count = sum(1 for r in runs if r.get("status") == "skipped")
        error_count = sum(1 for r in runs if r.get("status") == "error")

        summary_parts = [
            f"Last {total} activity turns: {ok_count} ok, {skip_count} skipped, {error_count} errors",
        ]

        # Show recent summaries for context
        recent_ok = [r for r in runs if r.get("status") == "ok"][-5:]
        if recent_ok:
            summary_parts.append("\nRecent successful turns:")
            for r in recent_ok:
                ts = r.get("ts", "?")
                summary = r.get("summary", "")[:150]
                elapsed = r.get("elapsed_s", "?")
                summary_parts.append(f"  [{ts}] ({elapsed}s) {summary}")

        recent_errors = [r for r in runs if r.get("status") == "error"][-3:]
        if recent_errors:
            summary_parts.append("\nRecent errors:")
            for r in recent_errors:
                ts = r.get("ts", "?")
                err = r.get("error", "")[:150]
                summary_parts.append(f"  [{ts}] {err}")

        # Current active rules for cross-reference
        active_rules = self._store.get_active_rules()
        if active_rules:
            summary_parts.append(f"\nActive rules: {len(active_rules)}")
            for rule in active_rules[:5]:
                summary_parts.append(f"  [{rule.id}] {rule.confidence:.0%} {rule.hypothesis[:80]}")

        summary_parts.append(
            "\nReflect on these outcomes. Consider:\n"
            "- Are there patterns in what succeeded vs. failed?\n"
            "- Should any existing rules be evaluated up or down?\n"
            "- Is there a new rule worth proposing?\n"
            "Use 'propose', 'evaluate', or 'retire' based on your analysis."
        )

        return ToolResult.ok("\n".join(summary_parts))
