"""Tool: query and update user profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from vex.personality.user_profile import UserFact, UserProfileStore

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class UserProfileTool:
    """Query and manage user profiles — what Vex knows about each person."""

    def __init__(self, store: UserProfileStore) -> None:
        self._store = store

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="user_profile",
            description=(
                "Query and manage user profiles. Use 'get' to see what you know about a user. "
                "Use 'add_fact' to record something new you learned. Use 'add_interest' to "
                "note a user's interest. Use 'set_preference' to record a preference. "
                "Use 'set_topics' to set topics you want to explore with them. "
                "Use 'list' to see all known users."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "get", "add_fact", "add_interest",
                            "set_preference", "set_topics", "list",
                        ],
                        "description": "Action to perform.",
                    },
                    "user_id": {
                        "type": "integer",
                        "description": "User ID (required for all except 'list').",
                    },
                    "fact": {
                        "type": "string",
                        "description": "Fact text (for add_fact).",
                    },
                    "category": {
                        "type": "string",
                        "description": "Fact category: work, family, hobbies, location, etc.",
                    },
                    "interest": {
                        "type": "string",
                        "description": "Interest/topic name (for add_interest).",
                    },
                    "key": {
                        "type": "string",
                        "description": "Preference key (for set_preference).",
                    },
                    "value": {
                        "type": "string",
                        "description": "Preference value (for set_preference).",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Topics to explore (for set_topics).",
                    },
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.WRITE_LOCAL,
            group="personality",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments["action"]

        if action == "list":
            return self._action_list()

        user_id = arguments.get("user_id")
        if not user_id:
            return ToolResult.fail("'user_id' is required. Use action='list' to see all users.")

        if action == "get":
            return self._action_get(user_id)
        elif action == "add_fact":
            return self._action_add_fact(user_id, arguments)
        elif action == "add_interest":
            return self._action_add_interest(user_id, arguments)
        elif action == "set_preference":
            return self._action_set_preference(user_id, arguments)
        elif action == "set_topics":
            return self._action_set_topics(user_id, arguments)
        else:
            return ToolResult.fail(f"Unknown action: {action}")

    def _action_list(self) -> ToolResult:
        profiles = self._store.list_all()
        if not profiles:
            return ToolResult.ok("No user profiles found.")
        lines = ["Known users:"]
        for p in profiles:
            lines.append(
                f"  {p.user_id}: {p.display_name} "
                f"({p.interaction_count} interactions, {len(p.facts)} facts)"
            )
        return ToolResult.ok("\n".join(lines))

    def _action_get(self, user_id: int) -> ToolResult:
        profile = self._store.load(user_id)
        if not profile:
            return ToolResult.ok(f"No profile found for user {user_id}.")

        lines = [
            f"Profile for {profile.display_name} (ID: {profile.user_id})",
            f"  First seen: {profile.first_seen[:10] if profile.first_seen else 'unknown'}",
            f"  Last seen: {profile.last_seen[:10] if profile.last_seen else 'unknown'}",
            f"  Interactions: {profile.interaction_count}",
        ]

        if profile.telegram_username:
            lines.append(f"  Telegram: @{profile.telegram_username}")
        if profile.timezone:
            lines.append(f"  Timezone: {profile.timezone}")

        if profile.facts:
            lines.append(f"\n  Facts ({len(profile.facts)}):")
            for f in profile.facts[-15:]:
                lines.append(f"    [{f.category}] {f.fact} ({f.source}, {f.confidence:.0%})")

        if profile.interests:
            lines.append(f"\n  Interests: {', '.join(profile.interests)}")

        if profile.preferences:
            lines.append("\n  Preferences:")
            for k, v in profile.preferences.items():
                lines.append(f"    {k}: {v}")

        if profile.topics_to_explore:
            lines.append(f"\n  Topics to explore: {', '.join(profile.topics_to_explore)}")

        if profile.relationship_notes:
            lines.append(f"\n  Notes: {profile.relationship_notes}")

        return ToolResult.ok("\n".join(lines))

    def _action_add_fact(self, user_id: int, args: dict) -> ToolResult:
        fact_text = args.get("fact")
        if not fact_text:
            return ToolResult.fail("'fact' is required for add_fact.")

        fact = UserFact(
            fact=fact_text,
            source="stated",
            confidence=0.9,
            learned_at=datetime.now(timezone.utc).isoformat(),
            category=args.get("category", "general"),
        )
        added = self._store.add_fact(user_id, fact)
        if added:
            return ToolResult.ok(f"Added fact about user {user_id}: {fact_text}")
        return ToolResult.ok("Fact already known (or similar fact exists).")

    def _action_add_interest(self, user_id: int, args: dict) -> ToolResult:
        interest = args.get("interest")
        if not interest:
            return ToolResult.fail("'interest' is required for add_interest.")
        self._store.add_interest(user_id, interest)
        return ToolResult.ok(f"Added interest for user {user_id}: {interest}")

    def _action_set_preference(self, user_id: int, args: dict) -> ToolResult:
        key = args.get("key")
        value = args.get("value")
        if not key or not value:
            return ToolResult.fail("'key' and 'value' are required for set_preference.")
        profile = self._store.load(user_id)
        if not profile:
            return ToolResult.fail(f"No profile for user {user_id}.")
        profile.preferences[key] = value
        self._store.save(profile)
        return ToolResult.ok(f"Set preference {key}={value} for user {user_id}")

    def _action_set_topics(self, user_id: int, args: dict) -> ToolResult:
        topics = args.get("topics", [])
        if not topics:
            return ToolResult.fail("'topics' array is required for set_topics.")
        self._store.set_topic_to_explore(user_id, topics)
        return ToolResult.ok(f"Set {len(topics)} exploration topics for user {user_id}")
