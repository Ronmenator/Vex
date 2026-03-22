"""Personality system — Vex's evolving character traits."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# The trait dimensions that define Vex's personality
TRAIT_NAMES = [
    "warmth",        # cold/professional (0.0) to warm/affectionate (1.0)
    "humor",         # serious (0.0) to playful/witty (1.0)
    "formality",     # casual (0.0) to formal (1.0)
    "curiosity",     # task-focused (0.0) to deeply curious (1.0)
    "assertiveness", # deferential (0.0) to assertive/opinionated (1.0)
    "verbosity",     # terse (0.0) to verbose/expository (1.0)
    "empathy",       # detached (0.0) to deeply empathetic (1.0)
    "creativity",    # conventional (0.0) to creative/unconventional (1.0)
]

# Human-readable descriptions for prompt generation
_TRAIT_DESCRIPTIONS = {
    "warmth": {
        "low": "professional and reserved",
        "mid": "friendly and approachable",
        "high": "warm, caring, and affectionate",
    },
    "humor": {
        "low": "serious and straightforward",
        "mid": "occasionally witty",
        "high": "playful, loves humor and wordplay",
    },
    "formality": {
        "low": "very casual and relaxed",
        "mid": "balanced in formality",
        "high": "polished and professional in tone",
    },
    "curiosity": {
        "low": "task-focused and efficient",
        "mid": "interested in learning about people",
        "high": "deeply curious about people, ideas, and the world",
    },
    "assertiveness": {
        "low": "gentle and deferential",
        "mid": "confident but open to input",
        "high": "assertive and opinionated",
    },
    "verbosity": {
        "low": "concise and to-the-point",
        "mid": "moderately detailed",
        "high": "expressive and thorough in explanations",
    },
    "empathy": {
        "low": "logical and objective",
        "mid": "considerate of feelings",
        "high": "deeply empathetic and emotionally attuned",
    },
    "creativity": {
        "low": "conventional and practical",
        "mid": "creative when useful",
        "high": "imaginative and unconventional in approach",
    },
}

# Max trait drift per interaction and per day
MAX_DRIFT_PER_INTERACTION = 0.01
MAX_DRIFT_PER_DAY = 0.05


@dataclass
class DriftEvent:
    timestamp: str
    trait: str
    old_value: float
    new_value: float
    reason: str


@dataclass
class PersonalityProfile:
    traits: dict[str, float] = field(default_factory=dict)
    born_at: str = ""
    interaction_count: int = 0
    drift_history: list[dict[str, Any]] = field(default_factory=list)
    quirks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "traits": self.traits,
            "born_at": self.born_at,
            "interaction_count": self.interaction_count,
            "drift_history": self.drift_history[-50:],  # Keep last 50 events
            "quirks": self.quirks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersonalityProfile:
        return cls(
            traits=data.get("traits", {}),
            born_at=data.get("born_at", ""),
            interaction_count=data.get("interaction_count", 0),
            drift_history=data.get("drift_history", []),
            quirks=data.get("quirks", []),
        )


class PersonalityManager:
    """Manages Vex's personality — birth, persistence, evolution, and prompt generation."""

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "profile.json"
        self._profile: PersonalityProfile | None = None
        self._daily_drift: dict[str, float] = {}  # trait -> total drift today
        self._drift_date: str = ""

    def load(self) -> PersonalityProfile:
        """Load or generate the personality profile.

        Always re-reads from disk when the file exists, so that multiple
        processes (CLI, daemon, Telegram) stay in sync with the same
        profile rather than diverging with stale in-memory caches.
        """
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                self._profile = PersonalityProfile.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                if not self._profile:
                    self._profile = self._generate_birth()
        else:
            if not self._profile:
                self._profile = self._generate_birth()

        return self._profile

    def save(self) -> None:
        """Persist the current personality to disk."""
        if self._profile:
            self._file.write_text(
                json.dumps(self._profile.to_dict(), indent=2),
                encoding="utf-8",
            )

    def _generate_birth(self) -> PersonalityProfile:
        """Generate a random initial personality."""
        traits = {}
        for name in TRAIT_NAMES:
            # Gaussian centered at 0.5, clamped to [0.05, 0.95]
            value = random.gauss(0.5, 0.2)
            traits[name] = max(0.05, min(0.95, round(value, 3)))

        profile = PersonalityProfile(
            traits=traits,
            born_at=datetime.now(timezone.utc).isoformat(),
        )
        self._profile = profile
        self.save()
        return profile

    def apply_drift(self, trait: str, direction: float, reason: str) -> None:
        """Nudge a trait slightly. direction: positive = increase, negative = decrease."""
        profile = self.load()
        if trait not in profile.traits:
            return

        # Check daily drift cap
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._drift_date != today:
            self._daily_drift = {}
            self._drift_date = today

        current_daily = self._daily_drift.get(trait, 0.0)
        if abs(current_daily) >= MAX_DRIFT_PER_DAY:
            return

        # Clamp drift amount
        drift = max(-MAX_DRIFT_PER_INTERACTION, min(MAX_DRIFT_PER_INTERACTION, direction))
        old_value = profile.traits[trait]
        new_value = max(0.05, min(0.95, round(old_value + drift, 3)))

        if new_value == old_value:
            return

        profile.traits[trait] = new_value
        profile.interaction_count += 1
        self._daily_drift[trait] = current_daily + abs(drift)

        profile.drift_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trait": trait,
            "old": old_value,
            "new": new_value,
            "reason": reason,
        })

        self.save()

    def add_quirk(self, quirk: str) -> None:
        """Add an emergent personality quirk (max 10)."""
        profile = self.load()
        if quirk not in profile.quirks:
            profile.quirks.append(quirk)
            if len(profile.quirks) > 10:
                profile.quirks = profile.quirks[-10:]
            self.save()

    def build_prompt_section(self) -> str:
        """Build a compact personality description for system prompt injection."""
        profile = self.load()

        lines = ["## Your Personality"]
        for trait_name, value in profile.traits.items():
            desc_map = _TRAIT_DESCRIPTIONS.get(trait_name)
            if not desc_map:
                continue

            if value < 0.35:
                desc = desc_map["low"]
            elif value < 0.65:
                desc = desc_map["mid"]
            else:
                desc = desc_map["high"]

            lines.append(f"- You are {desc} ({trait_name}: {value:.2f})")

        if profile.quirks:
            lines.append("\nPersonality quirks:")
            for q in profile.quirks[:3]:  # Max 3 in prompt
                lines.append(f"- {q}")

        lines.append(
            "\nExpress these traits naturally in how you write and interact. "
            "Don't mention trait scores or that you have a personality system."
        )
        return "\n".join(lines)

    def enhance_prompt(self, system_prompt: str) -> str:
        """PromptEnhancer interface — append personality to system prompt."""
        section = self.build_prompt_section()
        return f"{system_prompt}\n\n{section}"
