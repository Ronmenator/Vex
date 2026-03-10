"""User profiling — Vex's knowledge about each person she interacts with."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class UserFact:
    fact: str
    source: str = "stated"       # "stated" | "inferred" | "observed"
    confidence: float = 0.8      # 0.0-1.0
    learned_at: str = ""         # ISO timestamp
    category: str = "general"    # "work", "family", "hobbies", "location", etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact": self.fact,
            "source": self.source,
            "confidence": self.confidence,
            "learned_at": self.learned_at,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserFact:
        return cls(
            fact=data.get("fact", ""),
            source=data.get("source", "stated"),
            confidence=data.get("confidence", 0.8),
            learned_at=data.get("learned_at", ""),
            category=data.get("category", "general"),
        )


@dataclass
class UserProfile:
    user_id: int = 0
    display_name: str = ""
    first_seen: str = ""
    last_seen: str = ""
    interaction_count: int = 0

    # Accumulated knowledge
    facts: list[UserFact] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    preferences: dict[str, str] = field(default_factory=dict)

    # Social context
    telegram_username: str | None = None
    timezone: str | None = None
    language: str | None = None

    # Relationship state
    relationship_notes: str = ""
    topics_to_explore: list[str] = field(default_factory=list)
    last_proactive_outreach: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "interaction_count": self.interaction_count,
            "facts": [f.to_dict() for f in self.facts],
            "interests": self.interests,
            "preferences": self.preferences,
            "telegram_username": self.telegram_username,
            "timezone": self.timezone,
            "language": self.language,
            "relationship_notes": self.relationship_notes,
            "topics_to_explore": self.topics_to_explore,
            "last_proactive_outreach": self.last_proactive_outreach,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserProfile:
        return cls(
            user_id=data.get("user_id", 0),
            display_name=data.get("display_name", ""),
            first_seen=data.get("first_seen", ""),
            last_seen=data.get("last_seen", ""),
            interaction_count=data.get("interaction_count", 0),
            facts=[UserFact.from_dict(f) for f in data.get("facts", [])],
            interests=data.get("interests", []),
            preferences=data.get("preferences", {}),
            telegram_username=data.get("telegram_username"),
            timezone=data.get("timezone"),
            language=data.get("language"),
            relationship_notes=data.get("relationship_notes", ""),
            topics_to_explore=data.get("topics_to_explore", []),
            last_proactive_outreach=data.get("last_proactive_outreach"),
        )


class UserProfileStore:
    """Manages per-user profiles on disk at .vex/users/{user_id}.json."""

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[int, UserProfile] = {}

    def _path_for(self, user_id: int) -> Path:
        return self._dir / f"{user_id}.json"

    def load(self, user_id: int) -> UserProfile | None:
        if user_id in self._cache:
            return self._cache[user_id]

        path = self._path_for(user_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profile = UserProfile.from_dict(data)
            self._cache[user_id] = profile
            return profile
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load profile for user %d: %s", user_id, e)
            return None

    def save(self, profile: UserProfile) -> None:
        self._cache[profile.user_id] = profile
        path = self._path_for(profile.user_id)
        path.write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_or_create(
        self, user_id: int, display_name: str, username: str | None = None
    ) -> UserProfile:
        profile = self.load(user_id)
        if profile:
            profile.display_name = display_name
            profile.last_seen = datetime.now(timezone.utc).isoformat()
            profile.interaction_count += 1
            if username:
                profile.telegram_username = username
            self.save(profile)
            return profile

        now = datetime.now(timezone.utc).isoformat()
        profile = UserProfile(
            user_id=user_id,
            display_name=display_name,
            first_seen=now,
            last_seen=now,
            interaction_count=1,
            telegram_username=username,
        )
        self.save(profile)
        return profile

    def add_fact(self, user_id: int, fact: UserFact) -> bool:
        """Add a fact to a user's profile. Returns False if duplicate."""
        profile = self.load(user_id)
        if not profile:
            return False

        # Simple dedup: check if the fact text is already stored (case-insensitive)
        fact_lower = fact.fact.lower()
        for existing in profile.facts:
            if existing.fact.lower() == fact_lower:
                return False
            # Substring overlap check
            if fact_lower in existing.fact.lower() or existing.fact.lower() in fact_lower:
                # Update with the newer/longer version
                if len(fact.fact) > len(existing.fact):
                    existing.fact = fact.fact
                    existing.learned_at = fact.learned_at
                    existing.confidence = max(existing.confidence, fact.confidence)
                    self.save(profile)
                return False

        if not fact.learned_at:
            fact.learned_at = datetime.now(timezone.utc).isoformat()
        profile.facts.append(fact)
        self.save(profile)
        return True

    def add_interest(self, user_id: int, interest: str) -> None:
        profile = self.load(user_id)
        if profile and interest.lower() not in [i.lower() for i in profile.interests]:
            profile.interests.append(interest)
            if len(profile.interests) > 30:
                profile.interests = profile.interests[-30:]
            self.save(profile)

    def set_topic_to_explore(self, user_id: int, topics: list[str]) -> None:
        profile = self.load(user_id)
        if profile:
            profile.topics_to_explore = topics[:10]
            self.save(profile)

    def list_all(self) -> list[UserProfile]:
        profiles = []
        for path in self._dir.glob("*.json"):
            try:
                user_id = int(path.stem)
                profile = self.load(user_id)
                if profile:
                    profiles.append(profile)
            except (ValueError, json.JSONDecodeError):
                continue
        return profiles

    def build_prompt_section(self, user_id: int) -> str | None:
        """Build a compact user context section for system prompt injection."""
        profile = self.load(user_id)
        if not profile:
            return None

        lines = ["## About This User"]
        lines.append(
            f"Name: {profile.display_name}. "
            f"First interaction: {profile.first_seen[:10] if profile.first_seen else 'unknown'}. "
            f"Total interactions: {profile.interaction_count}."
        )

        if profile.telegram_username:
            lines.append(f"Telegram: @{profile.telegram_username}")

        # Top facts (most recent, max 10)
        if profile.facts:
            sorted_facts = sorted(
                profile.facts, key=lambda f: f.learned_at, reverse=True
            )[:10]
            lines.append("\nKey facts you know about them:")
            for f in sorted_facts:
                source_tag = f"[{f.source}]" if f.source != "stated" else ""
                lines.append(f"- {f.fact} {source_tag}".strip())

        if profile.interests:
            lines.append(f"\nInterests: {', '.join(profile.interests[:15])}")

        if profile.preferences:
            prefs = [f"{k}: {v}" for k, v in list(profile.preferences.items())[:5]]
            lines.append(f"Preferences: {'; '.join(prefs)}")

        if profile.relationship_notes:
            lines.append(f"\nRelationship notes: {profile.relationship_notes}")

        if profile.topics_to_explore:
            lines.append(
                f"\nTopics you want to explore with them: "
                f"{', '.join(profile.topics_to_explore[:5])}"
            )

        return "\n".join(lines)
