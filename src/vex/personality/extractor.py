"""Fact extraction — extracts user facts from conversations asynchronously."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from vex.llm.base import LlmClient, Message

from .user_profile import UserFact, UserProfileStore

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
You are a fact extractor. Analyze the conversation below and extract any new facts \
about the user. Only extract facts that are explicitly stated or strongly implied. \
Do NOT fabricate or assume.

Categories: work, family, hobbies, location, education, tech, social, personality, health, other

Existing known facts about this user:
{existing_facts}

Return a JSON array of new facts (not already known). If no new facts, return [].
Format: [{"fact": "...", "category": "...", "confidence": 0.0-1.0}]

Return ONLY the JSON array, nothing else.\
"""

_INTEREST_PROMPT = """\
Based on this conversation, list any topics or subjects the user seems interested in. \
Return a JSON array of short strings. If none detected, return [].
Example: ["Python", "home automation", "cryptocurrency"]

Return ONLY the JSON array.\
"""

_TOPICS_PROMPT = """\
You are building a relationship with this user. Based on what you know about them \
and the recent conversation, suggest 3-5 topics or questions you could naturally \
bring up in future conversations to learn more about them.

Known facts: {existing_facts}
Known interests: {interests}

Return a JSON array of short topic/question strings.
Example: ["What projects are they working on at work?", "Their favorite hiking trails"]

Return ONLY the JSON array.\
"""


class FactExtractor:
    """Extracts user facts from conversations using lightweight LLM calls."""

    def __init__(self, llm: LlmClient, profiles: UserProfileStore) -> None:
        self._llm = llm
        self._profiles = profiles

    async def extract_and_update(
        self,
        user_id: int,
        user_message: str,
        assistant_response: str,
    ) -> None:
        """Extract facts from a conversation exchange and update the user profile."""
        profile = self._profiles.load(user_id)
        if not profile:
            return

        # Build existing facts summary for dedup
        existing = "\n".join(f"- {f.fact}" for f in profile.facts[-20:])
        if not existing:
            existing = "(none yet)"

        conversation = (
            f"User ({profile.display_name}): {user_message}\n"
            f"Assistant: {assistant_response}"
        )

        # Run fact extraction and interest detection in parallel via sequential calls
        # (We can't truly parallelize with a single LLM client, but keep it simple)
        await self._extract_facts(user_id, conversation, existing)
        await self._extract_interests(user_id, conversation)

        # Update exploration topics less frequently (every 10 interactions)
        if profile.interaction_count % 10 == 0:
            await self._update_topics(user_id, existing, profile.interests)

    async def _extract_facts(
        self, user_id: int, conversation: str, existing: str
    ) -> None:
        try:
            prompt = _EXTRACTION_PROMPT.format(existing_facts=existing)
            messages = [
                Message(role="system", content=prompt),
                Message(role="user", content=conversation),
            ]
            response = await self._llm.chat(messages)
            result_text = (response.content or "").strip()

            facts = self._parse_json_array(result_text)
            now = datetime.now(timezone.utc).isoformat()

            for item in facts:
                if not isinstance(item, dict) or "fact" not in item:
                    continue
                fact = UserFact(
                    fact=item["fact"],
                    source="inferred",
                    confidence=min(1.0, max(0.0, item.get("confidence", 0.7))),
                    learned_at=now,
                    category=item.get("category", "general"),
                )
                self._profiles.add_fact(user_id, fact)

        except Exception as e:
            logger.debug("Fact extraction failed for user %d: %s", user_id, e)

    async def _extract_interests(self, user_id: int, conversation: str) -> None:
        try:
            messages = [
                Message(role="system", content=_INTEREST_PROMPT),
                Message(role="user", content=conversation),
            ]
            response = await self._llm.chat(messages)
            result_text = (response.content or "").strip()

            interests = self._parse_json_array(result_text)
            for interest in interests:
                if isinstance(interest, str) and interest.strip():
                    self._profiles.add_interest(user_id, interest.strip())

        except Exception as e:
            logger.debug("Interest extraction failed for user %d: %s", user_id, e)

    async def _update_topics(
        self, user_id: int, existing_facts: str, interests: list[str]
    ) -> None:
        try:
            prompt = _TOPICS_PROMPT.format(
                existing_facts=existing_facts,
                interests=", ".join(interests[:10]) if interests else "(none)",
            )
            messages = [
                Message(role="system", content=prompt),
                Message(role="user", content="Suggest topics to explore."),
            ]
            response = await self._llm.chat(messages)
            result_text = (response.content or "").strip()

            topics = self._parse_json_array(result_text)
            valid = [t for t in topics if isinstance(t, str) and t.strip()]
            if valid:
                self._profiles.set_topic_to_explore(user_id, valid[:5])

        except Exception as e:
            logger.debug("Topic update failed for user %d: %s", user_id, e)

    @staticmethod
    def _parse_json_array(text: str) -> list[Any]:
        """Parse a JSON array from LLM output, handling markdown code fences."""
        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            # Try to find array in the text
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    result = json.loads(text[start:end])
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    pass

        return []
