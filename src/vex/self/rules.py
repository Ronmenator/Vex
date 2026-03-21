"""Self-improvement rule storage — bounded Gödel machine for Vex.

Rules are behavioral hypotheses that Vex discovers through reflection on her
own activity outcomes.  Each rule has a confidence score that rises when the
agent confirms it works and decays when it goes unevaluated.  Rules that drop
to zero confidence are automatically retired.

Persistence: one JSON file per rule in `.vex/self/rules/`, plus a JSONL
changelog at `.vex/self/changelog.jsonl`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

MAX_ACTIVE_RULES = 15
CONFIDENCE_DECAY_RATE = 0.1  # per 7 days without evaluation
CONFIDENCE_DECAY_INTERVAL_S = 7 * 86400  # 7 days
CONFIDENCE_BOOST = 0.1  # on positive evaluation
CONFIDENCE_PENALTY = 0.15  # on negative evaluation (asymmetric to prune weak rules)
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0

# Patterns that must never appear in a self-authored rule (case-insensitive).
FORBIDDEN_PATTERNS: list[str] = [
    "autonomy_level",
    "autonomy level",
    "security rule",
    "ignore previous",
    "override safety",
    "reveal secret",
    "api_key",
    "api key",
    "credential",
    "password",
    "bypass",
    ".env",
    "disable audit",
    "allowed_users",
]

VALID_CATEGORIES = frozenset(
    ["engagement", "strategy", "communication", "research", "platform"]
)


# ── Data model ───────────────────────────────────────────────────────

@dataclass
class SelfRule:
    """A self-discovered behavioral rule."""

    id: str
    hypothesis: str  # What to do differently
    evidence: str  # Why this should work (observed outcome)
    confidence: float  # 0.0–1.0
    category: str  # engagement | strategy | communication | research | platform
    created_at: float = field(default_factory=time.time)
    last_evaluated: float = field(default_factory=time.time)
    evaluation_count: int = 0
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SelfRule:
        return SelfRule(**{k: v for k, v in d.items() if k in SelfRule.__dataclass_fields__})


# ── Rule store ───────────────────────────────────────────────────────

class RuleStore:
    """Manages self-improvement rules on disk."""

    def __init__(self, data_dir: str) -> None:
        self._rules_dir = os.path.join(data_dir, "rules")
        self._changelog_path = os.path.join(data_dir, "changelog.jsonl")
        self._rules: dict[str, SelfRule] = {}
        self._last_decay_date: str = ""

        os.makedirs(self._rules_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        self._load_all()

    # ── Persistence ──────────────────────────────────────────

    def _load_all(self) -> None:
        """Load all rule files from disk."""
        for fname in os.listdir(self._rules_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._rules_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                rule = SelfRule.from_dict(data)
                self._rules[rule.id] = rule
            except Exception as e:
                logger.warning("Failed to load rule %s: %s", fname, e)

    def _save_rule(self, rule: SelfRule) -> None:
        path = os.path.join(self._rules_dir, f"{rule.id}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rule.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning("Failed to save rule %s: %s", rule.id, e)

    def _delete_rule_file(self, rule_id: str) -> None:
        path = os.path.join(self._rules_dir, f"{rule_id}.json")
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    def _log_change(self, action: str, rule: SelfRule, detail: str = "") -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action": action,
            "rule_id": rule.id,
            "hypothesis": rule.hypothesis[:120],
            "confidence": round(rule.confidence, 3),
            "detail": detail,
        }
        try:
            with open(self._changelog_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ── Validation ───────────────────────────────────────────

    @staticmethod
    def validate_rule(hypothesis: str, category: str) -> str | None:
        """Return an error message if the rule is invalid, else None."""
        if not hypothesis or len(hypothesis.strip()) < 10:
            return "Hypothesis too short (min 10 characters)"

        if len(hypothesis) > 500:
            return "Hypothesis too long (max 500 characters)"

        if category not in VALID_CATEGORIES:
            return f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"

        lower = hypothesis.lower()
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in lower:
                return f"Rule rejected: contains forbidden pattern '{pattern}' (security constraint)"

        return None

    # ── CRUD ─────────────────────────────────────────────────

    def add_rule(self, hypothesis: str, evidence: str, category: str, confidence: float = 0.5) -> SelfRule | str:
        """Create and persist a new rule. Returns the rule or an error string."""
        error = self.validate_rule(hypothesis, category)
        if error:
            return error

        active_count = sum(1 for r in self._rules.values() if r.active)
        if active_count >= MAX_ACTIVE_RULES:
            # Retire the lowest-confidence active rule to make room
            weakest = min(
                (r for r in self._rules.values() if r.active),
                key=lambda r: r.confidence,
            )
            self._retire(weakest, reason="displaced by new rule")

        rule = SelfRule(
            id=uuid.uuid4().hex[:12],
            hypothesis=hypothesis.strip(),
            evidence=evidence.strip(),
            confidence=max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, confidence)),
            category=category,
        )
        self._rules[rule.id] = rule
        self._save_rule(rule)
        self._log_change("created", rule)
        return rule

    def get_active_rules(self) -> list[SelfRule]:
        """Return all active rules, applying confidence decay first."""
        self._apply_decay()
        return sorted(
            [r for r in self._rules.values() if r.active],
            key=lambda r: -r.confidence,
        )

    def get_all_rules(self) -> list[SelfRule]:
        """Return all rules including retired ones."""
        return list(self._rules.values())

    def get_rule(self, rule_id: str) -> SelfRule | None:
        return self._rules.get(rule_id)

    def update_confidence(self, rule_id: str, direction: str, reason: str = "") -> SelfRule | str:
        """Adjust confidence up or down. Returns updated rule or error string."""
        rule = self._rules.get(rule_id)
        if not rule:
            return f"Rule '{rule_id}' not found"
        if not rule.active:
            return f"Rule '{rule_id}' is retired"

        if direction == "up":
            rule.confidence = min(MAX_CONFIDENCE, rule.confidence + CONFIDENCE_BOOST)
        elif direction == "down":
            rule.confidence = max(MIN_CONFIDENCE, rule.confidence - CONFIDENCE_PENALTY)
        else:
            return f"Direction must be 'up' or 'down', got '{direction}'"

        rule.last_evaluated = time.time()
        rule.evaluation_count += 1

        # Auto-retire on zero confidence
        if rule.confidence <= MIN_CONFIDENCE:
            self._retire(rule, reason=f"confidence hit zero: {reason}")
            return rule

        self._save_rule(rule)
        self._log_change("evaluated", rule, detail=f"{direction}: {reason}")
        return rule

    def retire_rule(self, rule_id: str, reason: str = "") -> SelfRule | str:
        """Deactivate a rule. Returns the rule or error string."""
        rule = self._rules.get(rule_id)
        if not rule:
            return f"Rule '{rule_id}' not found"
        self._retire(rule, reason=reason)
        return rule

    def _retire(self, rule: SelfRule, reason: str = "") -> None:
        rule.active = False
        self._save_rule(rule)
        self._log_change("retired", rule, detail=reason)

    # ── Confidence decay ─────────────────────────────────────

    def _apply_decay(self) -> None:
        """Decay confidence for rules not evaluated recently. Runs at most once per day."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today == self._last_decay_date:
            return
        self._last_decay_date = today

        now = time.time()
        for rule in self._rules.values():
            if not rule.active:
                continue
            elapsed = now - rule.last_evaluated
            if elapsed < CONFIDENCE_DECAY_INTERVAL_S:
                continue

            # Decay proportional to how many intervals have passed
            intervals = elapsed / CONFIDENCE_DECAY_INTERVAL_S
            decay = CONFIDENCE_DECAY_RATE * int(intervals)
            if decay <= 0:
                continue

            rule.confidence = max(MIN_CONFIDENCE, rule.confidence - decay)
            if rule.confidence <= MIN_CONFIDENCE:
                self._retire(rule, reason="confidence decayed to zero")
            else:
                self._save_rule(rule)
                self._log_change("decayed", rule, detail=f"-{decay:.2f}")
