"""Interactive onboarding — ask questions to shape the bot's personality and name.

Runs as a standalone CLI flow (``vex onboard``) that collects answers, feeds
them to the LLM to derive trait values and a name, then writes the profile.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

from vex.personality.traits import TRAIT_NAMES, PersonalityManager, PersonalityProfile
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Questions ─────────────────────────────────────────────────────────
# Each question targets one or more personality dimensions.
# The LLM will interpret the free-text answers holistically.

ONBOARDING_QUESTIONS: list[dict[str, str]] = [
    {
        "key": "name",
        "question": (
            "Let's give your AI a name. What would you like to call it? "
            "(Leave blank for a random suggestion)"
        ),
    },
    {
        "key": "tone",
        "question": (
            "How should your AI talk? For example: casual and witty, "
            "formal and precise, warm and encouraging, blunt and direct..."
        ),
    },
    {
        "key": "curiosity",
        "question": (
            "Should your AI be curious about you and the world, or stay "
            "laser-focused on tasks? (e.g., 'ask me about my day' vs "
            "'just get the job done')"
        ),
    },
    {
        "key": "humor",
        "question": (
            "How much humor? None, occasional dry wit, full-on playful, "
            "or somewhere in between?"
        ),
    },
    {
        "key": "assertiveness",
        "question": (
            "When it disagrees with you, should it push back or defer? "
            "(e.g., 'challenge me' vs 'go with what I say')"
        ),
    },
    {
        "key": "verbosity",
        "question": (
            "Short and concise responses, or detailed explanations? "
            "(e.g., 'terse' vs 'thorough')"
        ),
    },
    {
        "key": "empathy",
        "question": (
            "Should it be emotionally attuned and supportive, or "
            "keep things logical and objective?"
        ),
    },
    {
        "key": "creativity",
        "question": (
            "Conventional and practical, or creative and unconventional "
            "in how it approaches problems?"
        ),
    },
]

# ── LLM interpretation prompt ────────────────────────────────────────

_INTERPRET_PROMPT = """\
You are a personality calibration system. Given the user's answers to onboarding \
questions, produce a JSON object with exactly these fields:

{{
  "name": "<the bot's chosen name — use the user's choice if given, otherwise \
invent a short, memorable name that fits the described personality>",
  "traits": {{
    "warmth": <0.0-1.0>,
    "humor": <0.0-1.0>,
    "formality": <0.0-1.0>,
    "curiosity": <0.0-1.0>,
    "assertiveness": <0.0-1.0>,
    "verbosity": <0.0-1.0>,
    "empathy": <0.0-1.0>,
    "creativity": <0.0-1.0>
  }}
}}

Trait scale:
- 0.0 = minimum (e.g., warmth 0.0 = cold/professional)
- 0.5 = balanced/moderate
- 1.0 = maximum (e.g., warmth 1.0 = very warm and affectionate)

Rules:
- Output ONLY the JSON object, no explanation, no markdown fences.
- Infer traits holistically from ALL answers, not one-to-one.
- Clamp values to [0.05, 0.95].
- If an answer is vague or empty, default that dimension to 0.50.

User's answers:
{answers}
"""


async def run_onboarding(
    personality_manager: PersonalityManager,
    llm: Any,
    ask: Callable[[str], Awaitable[str]],
    tell: Callable[[str], Awaitable[None] | None],
) -> PersonalityProfile:
    """Run the interactive onboarding flow.

    Parameters
    ----------
    personality_manager : PersonalityManager
        Where to save the resulting profile.
    llm : LLM client
        Used to interpret answers into trait values.
    ask : async (question) -> answer
        Callback to prompt the user for input.
    tell : (message) -> None
        Callback to display a message to the user.
    """
    result = tell("\n  Welcome! Let's set up your AI's personality.\n"
                  "  Answer a few quick questions — there are no wrong answers.\n")
    if hasattr(result, "__await__"):
        await result

    # Collect answers
    answers: dict[str, str] = {}
    for item in ONBOARDING_QUESTIONS:
        answer = await ask(f"  {item['question']}")
        answers[item["key"]] = answer.strip() if answer else ""

    result = tell("\n  Calibrating personality...")
    if hasattr(result, "__await__"):
        await result

    # Format answers for LLM
    answer_text = "\n".join(
        f"- {item['key']}: {answers.get(item['key'], '(no answer)')}"
        for item in ONBOARDING_QUESTIONS
    )
    prompt = _INTERPRET_PROMPT.format(answers=answer_text)

    # Ask LLM to interpret
    from vex.llm.base import Message

    messages = [Message(role="user", content=prompt)]
    response_text = ""
    async for event in llm.stream(messages, system=None):
        if event.text_delta:
            response_text += event.text_delta

    # Parse LLM response
    profile = _parse_llm_response(response_text, answers)

    # Save
    personality_manager._profile = profile
    personality_manager.save()

    # Show result
    summary_lines = [f"\n  Name: {profile.name}", "  Traits:"]
    for trait, value in profile.traits.items():
        bar = "\u2588" * int(value * 10) + "\u2591" * (10 - int(value * 10))
        summary_lines.append(f"    {trait:<15} {bar} {value:.2f}")
    summary_lines.append("\n  Personality saved! Run the bot to start chatting.\n")

    result = tell("\n".join(summary_lines))
    if hasattr(result, "__await__"):
        await result

    return profile


def _parse_llm_response(
    response: str, answers: dict[str, str]
) -> PersonalityProfile:
    """Parse the LLM's JSON response into a PersonalityProfile."""
    # Strip markdown fences if present
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse onboarding LLM response, using defaults")
        data = {}

    # Extract name
    name = data.get("name", "").strip()
    if not name:
        name = answers.get("name", "").strip() or "Vex"

    # Extract traits with validation
    raw_traits = data.get("traits", {})
    traits: dict[str, float] = {}
    for t in TRAIT_NAMES:
        val = raw_traits.get(t, 0.5)
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = 0.5
        traits[t] = max(0.05, min(0.95, round(val, 3)))

    return PersonalityProfile(
        name=name,
        traits=traits,
        born_at=datetime.now(timezone.utc).isoformat(),
    )
