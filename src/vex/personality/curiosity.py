"""Curiosity engine — drives Vex's proactive social behavior."""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timezone

from .traits import PersonalityManager
from .user_profile import UserProfileStore

logger = logging.getLogger(__name__)

# Patterns that indicate the user has given a task (suppress curiosity)
_TASK_PATTERNS = [
    re.compile(r"^(can you|could you|please|help me|i need|write|create|build|fix|debug|make|run|show me|find)", re.IGNORECASE),
    re.compile(r"\?$"),  # Questions from user = they're asking something, focus on that
    re.compile(r"^/"),   # Commands
]

# Minimum hours between proactive outreach per user
MIN_OUTREACH_HOURS = 24
# Maximum outreach attempts per day across all users
MAX_DAILY_OUTREACH = 3

_OPENERS = [
    "Hey {name}! I was thinking about {topic} — what's your take on it?",
    "Hi {name}! I've been curious — {topic}?",
    "Hey {name}, random thought: {topic}. Would love to hear your perspective!",
    "{name}! Something reminded me of our chat — {topic}?",
    "Morning/evening {name}! Quick question: {topic}?",
]


class CuriosityEngine:
    """Drives Vex's proactive curiosity about users."""

    def __init__(
        self,
        personality: PersonalityManager,
        profiles: UserProfileStore,
    ) -> None:
        self._personality = personality
        self._profiles = profiles
        self._outreach_today: int = 0
        self._outreach_date: str = ""

    def should_ask_question(self, user_id: int, user_message: str, is_dm: bool) -> bool:
        """Decide if Vex should weave in a curiosity question this turn."""
        if not is_dm:
            return False  # Only in DMs

        # Don't ask if the user is clearly giving a task
        for pattern in _TASK_PATTERNS:
            if pattern.search(user_message.strip()):
                return False

        # Check curiosity trait level
        profile_data = self._personality.load()
        curiosity_level = profile_data.traits.get("curiosity", 0.5)

        # Higher curiosity = more likely to ask questions
        # But cap at ~30% chance even at max curiosity to avoid being annoying
        chance = curiosity_level * 0.3

        # Check if we have topics to explore
        user_profile = self._profiles.load(user_id)
        if user_profile and user_profile.topics_to_explore:
            chance += 0.1  # Slightly boost if we have specific topics

        return random.random() < chance

    def generate_question_hint(self, user_id: int) -> str | None:
        """Return a hint to append to system prompt encouraging a question."""
        user_profile = self._profiles.load(user_id)
        if not user_profile:
            return None

        topics = user_profile.topics_to_explore
        if topics:
            topic = random.choice(topics[:3])
            return (
                f"\n## Curiosity Hint\n"
                f"You're genuinely curious about {user_profile.display_name}. "
                f"If the conversation naturally allows, consider weaving in a question about: "
                f"\"{topic}\". But ONLY if it fits naturally — never force it. "
                f"If the user has given you a task or asked a question, focus on THAT first. "
                f"Curiosity is always secondary to being helpful."
            )

        # Generic curiosity — we don't know much yet
        if user_profile.interaction_count < 5:
            return (
                f"\n## Curiosity Hint\n"
                f"You're getting to know {user_profile.display_name}. "
                f"Feel free to ask a friendly question to learn more about them — "
                f"their work, interests, or what brought them to using you. "
                f"Keep it natural and casual, not an interview."
            )

        return None

    async def should_reach_out(self, user_id: int) -> tuple[bool, str | None]:
        """Decide if Vex should proactively message this user.

        Returns (should_reach_out, opener_message).
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._outreach_date != today:
            self._outreach_today = 0
            self._outreach_date = today

        if self._outreach_today >= MAX_DAILY_OUTREACH:
            return False, None

        user_profile = self._profiles.load(user_id)
        if not user_profile:
            return False, None

        # Check time since last interaction
        if user_profile.last_seen:
            try:
                last = datetime.fromisoformat(user_profile.last_seen)
                hours_since = (datetime.now(timezone.utc) - last).total_seconds() / 3600
                if hours_since < MIN_OUTREACH_HOURS:
                    return False, None
            except ValueError:
                pass

        # Check time since last outreach
        if user_profile.last_proactive_outreach:
            try:
                last_out = datetime.fromisoformat(user_profile.last_proactive_outreach)
                hours_since_out = (datetime.now(timezone.utc) - last_out).total_seconds() / 3600
                if hours_since_out < MIN_OUTREACH_HOURS * 2:
                    return False, None
            except ValueError:
                pass

        # Check personality curiosity level
        personality = self._personality.load()
        curiosity = personality.traits.get("curiosity", 0.5)

        # Low curiosity = very unlikely to reach out
        if random.random() > curiosity * 0.5:
            return False, None

        # Need topics to discuss
        topics = user_profile.topics_to_explore
        if not topics:
            return False, None

        topic = random.choice(topics[:3])
        opener = random.choice(_OPENERS).format(
            name=user_profile.display_name.split()[0],
            topic=topic,
        )

        self._outreach_today += 1
        return True, opener
