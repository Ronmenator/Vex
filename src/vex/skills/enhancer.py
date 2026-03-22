"""Skills prompt enhancer — injects relevant skill instructions into the system prompt.

Design philosophy (vs Claude Code's tool-based approach):
- **No extra tool needed**: skills are injected as prompt context automatically.
- **Trigger-based matching**: each skill declares keywords/phrases that activate it.
  When the user's message (or conversation context) matches a trigger, the full
  skill instructions are injected.  ``always: true`` skills are injected every turn.
- **Progressive disclosure**: the prompt always includes a compact index of all
  available skills (name + description).  Full instructions are only injected for
  triggered/always-on skills, keeping the prompt lean.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from vex.skills.loader import Skill, SkillLoader

logger = logging.getLogger(__name__)

# Budget: max chars of skill body injected per turn (prevents prompt bloat)
MAX_SKILL_BODY_CHARS = 8000


class SkillsEnhancer:
    """Prompt enhancer that loads .md skill files and injects relevant ones.

    Implements both the method-based interface (``enhance_prompt``) and the
    callable interface (``__call__``) so it works with the agent loop's
    two-pattern dispatch.
    """

    def __init__(self, skills_dir: str | Path) -> None:
        self._loader = SkillLoader(skills_dir)
        self._skills: list[Skill] | None = None  # Lazy-loaded

    @property
    def skills_dir(self) -> Path:
        return self._loader.directory

    def reload(self) -> None:
        """Force reload of skill files from disk."""
        self._skills = None

    def _ensure_loaded(self) -> list[Skill]:
        if self._skills is None:
            self._skills = self._loader.load_all()
            if self._skills:
                logger.info(
                    "Loaded %d skill(s) from %s",
                    len(self._skills),
                    self._loader.directory,
                )
        return self._skills

    def enhance_prompt(self, system_prompt: str) -> str:
        """PromptEnhancer interface — append skill index + always-on skills."""
        return self._enhance(system_prompt, user_message=None)

    def __call__(self, system_prompt: str, conversation: Any) -> str:
        """Callable interface — has access to conversation for context matching."""
        # Extract the last user message for trigger matching
        user_message = None
        if hasattr(conversation, "_messages") and conversation._messages:
            for msg in reversed(conversation._messages):
                if msg.role == "user":
                    user_message = msg.content
                    break
        return self._enhance(system_prompt, user_message=user_message)

    def _enhance(self, system_prompt: str, user_message: str | None) -> str:
        skills = self._ensure_loaded()
        if not skills:
            return system_prompt

        # Determine which skills to fully inject
        triggered: list[Skill] = []
        available: list[Skill] = []

        for skill in skills:
            if skill.always:
                triggered.append(skill)
            elif user_message and self._matches_triggers(skill, user_message):
                triggered.append(skill)
            else:
                available.append(skill)

        # Build the skills section
        lines: list[str] = ["\n\n## Skills"]

        # Always show the full index so the LLM knows what's available
        if available:
            lines.append(
                "You have the following skills available. When the user's "
                "request matches one, follow its instructions:"
            )
            for skill in available:
                lines.append(skill.summary)

        # Inject full body for triggered/always-on skills
        budget = MAX_SKILL_BODY_CHARS
        for skill in triggered:
            body = skill.body
            if len(body) > budget:
                body = body[:budget] + "\n\n_(skill truncated)_"
                budget = 0
            else:
                budget -= len(body)

            lines.append(f"\n### Skill: {skill.name}")
            lines.append(body)

        # Only append if we have something beyond the header
        if len(lines) > 1:
            return system_prompt + "\n".join(lines)

        return system_prompt

    @staticmethod
    def _matches_triggers(skill: Skill, text: str) -> bool:
        """Check if any of the skill's trigger phrases appear in the text."""
        text_lower = text.lower()
        return any(trigger in text_lower for trigger in skill.triggers)
