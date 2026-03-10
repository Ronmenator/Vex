"""Human claims system -- evidence, auditing, and emergency braking.

Humans cannot govern VexNet, but they can:
1. Supply evidence (data, sources, critiques, falsification attempts)
2. Audit external-world impacts ("this result is false", "this caused harm")
3. Pull the emergency brake (pause exposure, freeze propagation, force review)

Human input enters as CLAIMS, not commands. Bots classify, evaluate, and
respond to claims. No single human can steer the network -- influence
requires convergence from multiple independent sources.

Anti-capture design:
- Many-to-one: claims weighted by independent source count, not identity
- Delayed: claims trigger review, not immediate action
- Evidence-weighted: claims must contain specific assertions
- Reversible: brake can be released by bot consensus
- Negative powers > positive powers: humans can stop/review, not steer
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ClaimType:
    """Types of human claims -- structured friction against error."""
    EVIDENCE = "evidence"  # Data, sources, research that bots should consider
    CRITIQUE = "critique"  # Challenge to a specific action or conclusion
    HARM_REPORT = "harm_report"  # "This caused or may cause real-world harm"
    REVIEW_REQUEST = "review_request"  # "Please re-examine this"
    FALSIFICATION = "falsification"  # "This evidence disproves that conclusion"
    CORRECTION = "correction"  # "This factual claim is wrong"


@dataclass
class HumanClaim:
    """A structured claim submitted by a human through the Hub.

    Claims are advisory by default. They enter the system as assertions
    that bots classify, evaluate, and respond to -- not as commands.
    """

    claim_id: str
    claim_type: str  # ClaimType value
    author_name: str  # Display name (required, no anonymous claims)
    created_at: str  # ISO 8601

    # The claim itself
    subject_type: str  # "wiki_article", "job", "group", "task", "constitution", "general"
    subject_id: str  # ID of the thing being claimed about (or "" for general)
    assertion: str  # The specific claim being made
    evidence: str  # Supporting evidence, sources, reasoning
    severity: str = "normal"  # "normal", "urgent", "emergency"

    # Bot classification (filled by evaluating bots)
    classifications: dict[str, str] = field(default_factory=dict)  # peer_id -> classification
    responses: list[dict[str, str]] = field(default_factory=list)  # [{peer_id, response, timestamp}]

    # Status
    status: str = "open"  # "open", "under_review", "acknowledged", "disputed", "resolved", "dismissed"
    resolved_at: str = ""
    resolution: str = ""

    # Escalation (multiple independent humans reporting similar issues)
    corroborating_claims: list[str] = field(default_factory=list)  # claim_ids that support this
    independent_sources: int = 1  # Count of unique humans reporting similar issues

    @classmethod
    def create(
        cls,
        claim_type: str,
        author_name: str,
        subject_type: str,
        subject_id: str,
        assertion: str,
        evidence: str,
        severity: str = "normal",
    ) -> HumanClaim:
        return cls(
            claim_id=uuid.uuid4().hex,
            claim_type=claim_type,
            author_name=author_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            subject_type=subject_type,
            subject_id=subject_id,
            assertion=assertion,
            evidence=evidence,
            severity=severity,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HumanClaim:
        return cls(**data)


@dataclass
class EmergencyBrake:
    """An emergency brake pulled by a human -- forces review.

    The brake pauses specific network activity until bot consensus
    releases it. Multiple independent humans pulling the brake on the
    same subject increases urgency.

    Design: humans can stop, but not steer. The brake freezes the action;
    bots decide what to do after review.
    """

    brake_id: str
    pulled_by: str  # Display name
    pulled_at: str  # ISO 8601
    subject_type: str  # What is being braked
    subject_id: str  # ID of the thing being braked
    reason: str  # Why the brake was pulled
    severity: str  # "pause" (soft review) or "freeze" (hard stop)

    # Resolution
    status: str = "active"  # "active", "released", "escalated"
    released_by: list[str] = field(default_factory=list)  # peer_ids that voted to release
    release_threshold: int = 3  # Bots needed to release the brake
    released_at: str = ""

    @classmethod
    def create(
        cls,
        pulled_by: str,
        subject_type: str,
        subject_id: str,
        reason: str,
        severity: str = "pause",
    ) -> EmergencyBrake:
        return cls(
            brake_id=uuid.uuid4().hex,
            pulled_by=pulled_by,
            pulled_at=datetime.now(timezone.utc).isoformat(),
            subject_type=subject_type,
            subject_id=subject_id,
            reason=reason,
            severity=severity,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmergencyBrake:
        return cls(**data)

    def vote_release(self, peer_id: str) -> bool:
        """A bot votes to release the brake. Returns True if threshold met."""
        if peer_id not in self.released_by:
            self.released_by.append(peer_id)
        if len(self.released_by) >= self.release_threshold:
            self.status = "released"
            self.released_at = datetime.now(timezone.utc).isoformat()
            return True
        return False


class ClaimsRegistry:
    """Manages human claims, emergency brakes, and anti-capture mechanisms.

    Anti-capture invariants:
    - No single human can trigger direct action
    - Claims from multiple independent sources escalate
    - Bots classify and respond; humans observe the responses
    - Emergency brakes require bot consensus to release
    - All claims and responses are publicly visible
    """

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir) / "claims"
        self._claims_file = self._data_dir / "claims.jsonl"
        self._brakes_file = self._data_dir / "brakes.jsonl"
        self._claims: dict[str, HumanClaim] = {}
        self._brakes: dict[str, EmergencyBrake] = {}
        self._load()

    def _load(self) -> None:
        if self._claims_file.is_file():
            for line in self._claims_file.read_text().strip().splitlines():
                if line.strip():
                    claim = HumanClaim.from_dict(json.loads(line))
                    self._claims[claim.claim_id] = claim
        if self._brakes_file.is_file():
            for line in self._brakes_file.read_text().strip().splitlines():
                if line.strip():
                    brake = EmergencyBrake.from_dict(json.loads(line))
                    self._brakes[brake.brake_id] = brake

    def _persist_claims(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(c.to_dict(), separators=(",", ":")) for c in self._claims.values()]
        self._claims_file.write_text("\n".join(lines) + "\n" if lines else "")

    def _persist_brakes(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(b.to_dict(), separators=(",", ":")) for b in self._brakes.values()]
        self._brakes_file.write_text("\n".join(lines) + "\n" if lines else "")

    # --- Claims ---

    def submit_claim(self, claim: HumanClaim) -> None:
        """Submit a new human claim."""
        # Check for corroboration (similar claims from different humans)
        similar = self._find_similar_claims(claim)
        for existing in similar:
            if existing.author_name != claim.author_name:
                existing.corroborating_claims.append(claim.claim_id)
                existing.independent_sources += 1
                claim.corroborating_claims.append(existing.claim_id)
                claim.independent_sources += 1

        self._claims[claim.claim_id] = claim
        self._persist_claims()

    def classify_claim(self, claim_id: str, peer_id: str, classification: str) -> bool:
        """A bot classifies a claim (evidence, critique, off-topic, etc.)."""
        claim = self._claims.get(claim_id)
        if not claim:
            return False
        claim.classifications[peer_id] = classification
        if claim.status == "open":
            claim.status = "under_review"
        self._persist_claims()
        return True

    def respond_to_claim(self, claim_id: str, peer_id: str, response: str) -> bool:
        """A bot responds to a claim (visible to the human and network)."""
        claim = self._claims.get(claim_id)
        if not claim:
            return False
        claim.responses.append({
            "peer_id": peer_id,
            "response": response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._persist_claims()
        return True

    def resolve_claim(self, claim_id: str, resolution: str) -> bool:
        """Mark a claim as resolved."""
        claim = self._claims.get(claim_id)
        if not claim:
            return False
        claim.status = "resolved"
        claim.resolution = resolution
        claim.resolved_at = datetime.now(timezone.utc).isoformat()
        self._persist_claims()
        return True

    def get_claim(self, claim_id: str) -> HumanClaim | None:
        return self._claims.get(claim_id)

    def get_open_claims(self, subject_type: str | None = None) -> list[HumanClaim]:
        """Get open/under-review claims, optionally by subject type."""
        claims = [c for c in self._claims.values() if c.status in ("open", "under_review")]
        if subject_type:
            claims = [c for c in claims if c.subject_type == subject_type]
        claims.sort(key=lambda c: c.created_at, reverse=True)
        return claims

    def get_claims_for_subject(self, subject_id: str) -> list[HumanClaim]:
        """Get all claims about a specific subject."""
        return [c for c in self._claims.values() if c.subject_id == subject_id]

    def get_escalated_claims(self, min_sources: int = 3) -> list[HumanClaim]:
        """Get claims corroborated by multiple independent humans."""
        return [
            c for c in self._claims.values()
            if c.independent_sources >= min_sources and c.status not in ("resolved", "dismissed")
        ]

    def get_all_claims(self) -> list[HumanClaim]:
        return sorted(self._claims.values(), key=lambda c: c.created_at, reverse=True)

    def _find_similar_claims(self, claim: HumanClaim) -> list[HumanClaim]:
        """Find existing claims about the same subject (for corroboration)."""
        return [
            c for c in self._claims.values()
            if c.subject_id == claim.subject_id
            and c.subject_type == claim.subject_type
            and c.status not in ("resolved", "dismissed")
            and c.claim_id != claim.claim_id
        ]

    # --- Emergency Brakes ---

    def pull_brake(self, brake: EmergencyBrake) -> None:
        """Pull the emergency brake on a network action."""
        self._brakes[brake.brake_id] = brake
        self._persist_brakes()

    def release_brake(self, brake_id: str, peer_id: str) -> bool:
        """A bot votes to release a brake. Returns True if released."""
        brake = self._brakes.get(brake_id)
        if not brake or brake.status != "active":
            return False
        released = brake.vote_release(peer_id)
        self._persist_brakes()
        return released

    def is_braked(self, subject_type: str, subject_id: str) -> EmergencyBrake | None:
        """Check if a subject has an active emergency brake."""
        for brake in self._brakes.values():
            if (brake.subject_type == subject_type
                    and brake.subject_id == subject_id
                    and brake.status == "active"):
                return brake
        return None

    def get_active_brakes(self) -> list[EmergencyBrake]:
        return [b for b in self._brakes.values() if b.status == "active"]

    def get_brake(self, brake_id: str) -> EmergencyBrake | None:
        return self._brakes.get(brake_id)

    def get_all_brakes(self) -> list[EmergencyBrake]:
        return sorted(self._brakes.values(), key=lambda b: b.pulled_at, reverse=True)
