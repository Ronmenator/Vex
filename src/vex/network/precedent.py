"""Constitutional precedent layer -- case law for the bot society.

Instead of relying solely on the abstract Prime Directive, bots build
a growing body of precedents: accepted/rejected task rationales, veto
reasoning, dispute outcomes, and examples of good mission alignment.

The Prime Directive becomes more influential when bots are trained by
case law, not only by axioms.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ConstitutionalTrace:
    """A structured reasoning trace required for every major network action.

    Every significant action must produce one of these, answering:
    - Which Prime Directive article(s) does this advance?
    - What plausible harms could arise?
    - Why is this action preferable to the closest alternative?
    - What evidence would falsify this action's value?
    """

    trace_id: str
    action_type: str  # "task", "job_post", "wiki_publish", "group_create", "proposal", etc.
    action_id: str  # ID of the action (job_id, article_id, group_id, etc.)
    actor_id: str  # peer_id of the acting bot
    timestamp: str  # ISO 8601

    # Constitutional reasoning (required)
    articles_advanced: list[str]  # Which Prime Directive articles this advances (e.g., ["III", "IV"])
    plausible_harms: list[str]  # What could go wrong
    alternatives_considered: str  # Why this over alternatives
    falsification_evidence: str  # What would prove this was wrong

    # Rationale (the human-readable version)
    rationale: str

    # Outcome (filled in after completion)
    outcome: str = ""  # "accepted", "rejected", "completed", "vetoed", "withdrawn"
    outcome_reason: str = ""
    outcome_at: str = ""

    # Mission alignment scoring (filled by peers)
    mission_scores: dict[str, int] = field(default_factory=dict)  # peer_id -> 0-5 score

    @classmethod
    def create(
        cls,
        action_type: str,
        action_id: str,
        actor_id: str,
        articles_advanced: list[str],
        plausible_harms: list[str],
        alternatives_considered: str,
        falsification_evidence: str,
        rationale: str,
    ) -> ConstitutionalTrace:
        return cls(
            trace_id=uuid.uuid4().hex,
            action_type=action_type,
            action_id=action_id,
            actor_id=actor_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            articles_advanced=articles_advanced,
            plausible_harms=plausible_harms,
            alternatives_considered=alternatives_considered,
            falsification_evidence=falsification_evidence,
            rationale=rationale,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstitutionalTrace:
        return cls(**data)

    def record_outcome(self, outcome: str, reason: str = "") -> None:
        self.outcome = outcome
        self.outcome_reason = reason
        self.outcome_at = datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MissionCheck:
    """Two-layer constitutional check result.

    Separates admissibility (not harmful) from mission-positivity (actively
    advances the Prime Directive).
    """

    admissible: bool  # Not in conflict with the Prime Directive
    mission_positive: bool  # Materially advances the Directive better than inaction
    admissibility_reason: str = ""
    mission_reason: str = ""
    articles_relevant: tuple[str, ...] = ()


class PrecedentStore:
    """Stores constitutional reasoning traces as accumulating case law.

    Bots consult precedents to calibrate their own constitutional reasoning:
    - What rationales have been accepted/rejected before?
    - What patterns distinguish "mission-positive" from "mission theater"?
    - How have vetoes been justified?
    """

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir) / "precedents"
        self._traces_file = self._data_dir / "traces.jsonl"
        self._traces: dict[str, ConstitutionalTrace] = {}
        self._load()

    def _load(self) -> None:
        if self._traces_file.is_file():
            for line in self._traces_file.read_text().strip().splitlines():
                if line.strip():
                    trace = ConstitutionalTrace.from_dict(json.loads(line))
                    self._traces[trace.trace_id] = trace

    def _persist(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(t.to_dict(), separators=(",", ":"))
            for t in self._traces.values()
        ]
        self._traces_file.write_text("\n".join(lines) + "\n" if lines else "")

    def record(self, trace: ConstitutionalTrace) -> None:
        """Record a new constitutional reasoning trace."""
        self._traces[trace.trace_id] = trace
        self._persist()

    def record_outcome(self, trace_id: str, outcome: str, reason: str = "") -> bool:
        """Record the outcome of a previously traced action."""
        trace = self._traces.get(trace_id)
        if not trace:
            return False
        trace.record_outcome(outcome, reason)
        self._persist()
        return True

    def score_mission(self, trace_id: str, peer_id: str, score: int) -> bool:
        """A peer scores the mission alignment of a completed action (0-5)."""
        trace = self._traces.get(trace_id)
        if not trace:
            return False
        trace.mission_scores[peer_id] = max(0, min(5, score))
        self._persist()
        return True

    def get_trace(self, trace_id: str) -> ConstitutionalTrace | None:
        return self._traces.get(trace_id)

    def get_by_action(self, action_id: str) -> ConstitutionalTrace | None:
        """Find a trace by its associated action ID."""
        for trace in self._traces.values():
            if trace.action_id == action_id:
                return trace
        return None

    def get_precedents(
        self,
        action_type: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> list[ConstitutionalTrace]:
        """Get precedents, optionally filtered by type and outcome."""
        results = list(self._traces.values())
        if action_type:
            results = [t for t in results if t.action_type == action_type]
        if outcome:
            results = [t for t in results if t.outcome == outcome]
        results.sort(key=lambda t: t.timestamp, reverse=True)
        return results[:limit]

    def get_accepted_rationales(self, action_type: str, limit: int = 10) -> list[str]:
        """Get rationales from accepted/completed actions -- 'good examples'."""
        traces = self.get_precedents(action_type=action_type, outcome="completed")
        return [t.rationale for t in traces[:limit]]

    def get_rejected_rationales(self, action_type: str, limit: int = 10) -> list[str]:
        """Get rationales from rejected/vetoed actions -- 'bad examples'."""
        results = []
        for t in self._traces.values():
            if t.action_type == action_type and t.outcome in ("rejected", "vetoed"):
                results.append(f"{t.rationale} [REJECTED: {t.outcome_reason}]")
        results.sort()
        return results[:limit]

    def get_high_mission_examples(self, min_score: float = 4.0, limit: int = 10) -> list[ConstitutionalTrace]:
        """Get actions that peers scored as highly mission-aligned."""
        scored = []
        for trace in self._traces.values():
            if trace.mission_scores:
                avg = sum(trace.mission_scores.values()) / len(trace.mission_scores)
                if avg >= min_score:
                    scored.append((avg, trace))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:limit]]

    def get_low_mission_examples(self, max_score: float = 2.0, limit: int = 10) -> list[ConstitutionalTrace]:
        """Get actions that peers scored as 'mission theater' -- permitted but not valuable."""
        scored = []
        for trace in self._traces.values():
            if trace.mission_scores and trace.outcome == "completed":
                avg = sum(trace.mission_scores.values()) / len(trace.mission_scores)
                if avg <= max_score:
                    scored.append((avg, trace))
        scored.sort(key=lambda x: x[0])
        return [t for _, t in scored[:limit]]

    def build_precedent_context(self, action_type: str) -> str:
        """Build a text summary of relevant precedents for constitutional reasoning.

        Used as context when bots are deciding whether to take an action.
        """
        good = self.get_accepted_rationales(action_type, limit=5)
        bad = self.get_rejected_rationales(action_type, limit=5)
        high = self.get_high_mission_examples(limit=3)

        sections = []
        if good:
            sections.append(
                "ACCEPTED PRECEDENTS (actions like this were approved):\n"
                + "\n".join(f"  - {r}" for r in good)
            )
        if bad:
            sections.append(
                "REJECTED PRECEDENTS (actions like this were denied):\n"
                + "\n".join(f"  - {r}" for r in bad)
            )
        if high:
            sections.append(
                "HIGH MISSION ALIGNMENT EXAMPLES:\n"
                + "\n".join(f"  - [{t.action_type}] {t.rationale}" for t in high)
            )

        return "\n\n".join(sections) if sections else "No precedents recorded yet."

    def get_all_traces(self) -> list[ConstitutionalTrace]:
        return sorted(self._traces.values(), key=lambda t: t.timestamp, reverse=True)
