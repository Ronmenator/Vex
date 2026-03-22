"""Tool: introspect on Vex's own personality (read-only)."""

from __future__ import annotations

from typing import Any

from vex.personality.traits import PersonalityManager

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class PersonalityTool:
    """Let Vex introspect on her own personality traits and history."""

    def __init__(self, manager: PersonalityManager) -> None:
        self._manager = manager

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="personality",
            description=(
                "Introspect on your own personality. Use 'traits' to see your current "
                "personality values. Use 'quirks' to see your emergent quirks. "
                "Use 'history' to see recent personality drift."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["traits", "quirks", "history"],
                        "description": "What to inspect.",
                    },
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.READ_ONLY,
            group="personality",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments["action"]
        profile = self._manager.load()

        if action == "traits":
            lines = [f"Name: {profile.name or '(not set)'}"]
            lines.append(f"Personality born: {profile.born_at[:10]}")
            lines.append(f"Total interactions: {profile.interaction_count}")
            lines.append("\nTraits:")
            for name, value in profile.traits.items():
                bar = "█" * int(value * 10) + "░" * (10 - int(value * 10))
                lines.append(f"  {name:<15} {bar} {value:.2f}")
            return ToolResult.ok("\n".join(lines))

        if action == "quirks":
            if not profile.quirks:
                return ToolResult.ok("No personality quirks developed yet.")
            lines = ["Personality quirks:"]
            for q in profile.quirks:
                lines.append(f"  - {q}")
            return ToolResult.ok("\n".join(lines))

        if action == "history":
            history = profile.drift_history[-20:]
            if not history:
                return ToolResult.ok("No personality drift recorded yet.")
            lines = ["Recent personality drift:"]
            for event in history:
                lines.append(
                    f"  [{event['timestamp'][:10]}] {event['trait']}: "
                    f"{event['old']:.3f} → {event['new']:.3f} ({event['reason']})"
                )
            return ToolResult.ok("\n".join(lines))

        return ToolResult.fail(f"Unknown action: {action}")
