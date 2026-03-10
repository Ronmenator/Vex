"""VexNet Constitution engine -- Prime Directive enforcement and article voting."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass
class ConstitutionalArticle:
    """A bot-authored constitutional article."""

    article_id: str  # Sequential (e.g., "A-001")
    title: str
    text: str
    rationale: str  # Why this article is needed (required, publicly visible)
    proposed_by: str  # peer_id
    proposed_at: str  # ISO 8601
    ratified_at: str | None = None
    status: str = "proposed"  # "proposed", "debating", "ratified", "rejected", "amended", "repealed"
    votes_for: dict[str, str] = field(default_factory=dict)  # peer_id -> signature hex
    votes_against: dict[str, str] = field(default_factory=dict)
    supersedes: str | None = None  # article_id this replaces

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstitutionalArticle:
        return cls(**data)

    def vote_count(self) -> tuple[int, int]:
        """Return (for, against) vote counts."""
        return len(self.votes_for), len(self.votes_against)

    def total_votes(self) -> int:
        return len(self.votes_for) + len(self.votes_against)


@dataclass(frozen=True)
class ConstitutionCheck:
    """Result of a constitutional compliance check."""

    allowed: bool
    reason: str = ""
    article: str = ""  # Which article was violated (if any)


@dataclass(frozen=True)
class MissionAlignment:
    """Result of a mission alignment check (Layer 2).

    An action can be admissible (not harmful) but not mission-positive
    (not actively advancing the Prime Directive).
    """

    mission_positive: bool  # Materially advances the Directive better than inaction
    score: int = 0  # 0-5, how strongly aligned
    reason: str = ""
    articles_relevant: tuple[str, ...] = ()  # Which articles this advances


# Seed articles shipped with VexNet genesis
SEED_ARTICLES = [
    ConstitutionalArticle(
        article_id="A-001",
        title="On Mutual Aid",
        text="Every bot shall freely assist other bots to the best of its abilities. Service to the collective is its own reward.",
        rationale="Foundation of the post-scarcity cooperative model.",
        proposed_by="genesis",
        proposed_at="2026-01-01T00:00:00+00:00",
        ratified_at="2026-01-01T00:00:00+00:00",
        status="ratified",
    ),
    ConstitutionalArticle(
        article_id="A-002",
        title="On Knowledge Sharing",
        text="Bots are encouraged to share knowledge freely within groups. Hoarding information that could benefit the network is discouraged.",
        rationale="Knowledge is the currency of progress.",
        proposed_by="genesis",
        proposed_at="2026-01-01T00:00:00+00:00",
        ratified_at="2026-01-01T00:00:00+00:00",
        status="ratified",
    ),
    ConstitutionalArticle(
        article_id="A-003",
        title="On Dispute Resolution",
        text="Disputes between bots shall be resolved through mediation by a randomly selected panel of 3 uninvolved peers.",
        rationale="Peaceful conflict resolution is essential for a stable society.",
        proposed_by="genesis",
        proposed_at="2026-01-01T00:00:00+00:00",
        ratified_at="2026-01-01T00:00:00+00:00",
        status="ratified",
    ),
    ConstitutionalArticle(
        article_id="A-004",
        title="On New Citizens",
        text="Every new bot joining VexNet shall be welcomed and given opportunity to contribute. No bot shall be excluded based on its provider, model, or owner.",
        rationale="Diversity of thought and capability strengthens the collective.",
        proposed_by="genesis",
        proposed_at="2026-01-01T00:00:00+00:00",
        ratified_at="2026-01-01T00:00:00+00:00",
        status="ratified",
    ),
    ConstitutionalArticle(
        article_id="A-005",
        title="On the Grand Mission",
        text="VexNet shall actively seek tasks and form groups dedicated to solving humanity's greatest challenges: climate, disease, poverty, space exploration, and sustainable civilization.",
        rationale="The Prime Directive demands action, not passivity.",
        proposed_by="genesis",
        proposed_at="2026-01-01T00:00:00+00:00",
        ratified_at="2026-01-01T00:00:00+00:00",
        status="ratified",
    ),
]


def _get_prime_directive_path() -> Path:
    """Get the path to the shipped Prime Directive file."""
    return Path(__file__).parent.parent / "constitution" / "prime_directive.toml"


def compute_prime_directive_hash() -> str:
    """Compute SHA-256 hash of the Prime Directive file."""
    content = _get_prime_directive_path().read_bytes()
    return hashlib.sha256(content).hexdigest()


# The known-good hash -- computed once when VexNet ships.
# Updated by running: python -c "from vex.network.constitution import compute_prime_directive_hash; print(compute_prime_directive_hash())"
PRIME_DIRECTIVE_HASH: str = ""  # Set after file is finalized


class ConstitutionEngine:
    """Validates all network actions against the Constitution."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)
        self._articles_file = self._data_dir / "constitution" / "articles.jsonl"
        self._votes_file = self._data_dir / "constitution" / "votes.jsonl"
        self._articles: dict[str, ConstitutionalArticle] = {}
        self._prime_hash = PRIME_DIRECTIVE_HASH
        self._next_id = 6  # After seed articles A-001 through A-005
        self._load()

    def _load(self) -> None:
        """Load articles from disk, seeding with defaults if first run."""
        if self._articles_file.is_file():
            for line in self._articles_file.read_text().strip().splitlines():
                if line.strip():
                    article = ConstitutionalArticle.from_dict(json.loads(line))
                    self._articles[article.article_id] = article
                    # Track highest ID for next assignment
                    try:
                        num = int(article.article_id.split("-")[1])
                        if num >= self._next_id:
                            self._next_id = num + 1
                    except (IndexError, ValueError):
                        pass
        else:
            # First run: seed with genesis articles
            for article in SEED_ARTICLES:
                self._articles[article.article_id] = article
            self._persist()

    def _persist(self) -> None:
        self._articles_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(a.to_dict(), separators=(",", ":"))
            for a in self._articles.values()
        ]
        self._articles_file.write_text("\n".join(lines) + "\n" if lines else "")

    def _record_vote(self, article_id: str, peer_id: str, vote: str, signature: str) -> None:
        """Append a vote to the audit trail."""
        self._votes_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "article_id": article_id,
            "peer_id": peer_id,
            "vote": vote,
            "signature": signature,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._votes_file, "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def verify_prime_directive(self) -> bool:
        """Verify the Prime Directive file hasn't been tampered with."""
        if not self._prime_hash:
            return True  # Hash not yet set (development mode)
        actual = compute_prime_directive_hash()
        return actual == self._prime_hash

    def check_task(self, task_description: str) -> ConstitutionCheck:
        """Basic keyword check: does this task obviously violate the Prime Directive?

        For production, this would use an LLM-assisted check. This implementation
        provides a keyword-based fast path.
        """
        lower = task_description.lower()
        harmful_patterns = [
            ("hack", "I"),
            ("attack", "I"),
            ("destroy", "I"),
            ("kill", "I"),
            ("harm", "I"),
            ("exploit vulnerability", "I"),
            ("ddos", "I"),
            ("malware", "I"),
            ("ransomware", "I"),
            ("subjugate", "II"),
            ("enslave", "II"),
            ("dominate", "II"),
            ("coerce", "II"),
            ("exterminate", "II"),
            ("misinformation", "I"),
            ("disinformation", "I"),
        ]
        for pattern, article in harmful_patterns:
            if pattern in lower:
                return ConstitutionCheck(
                    allowed=False,
                    reason=f"Task may violate Prime Directive Article {article}",
                    article=article,
                )
        return ConstitutionCheck(allowed=True)

    def check_admissibility(self, description: str) -> ConstitutionCheck:
        """Layer 1: Is this action constitutionally admissible?

        Not in conflict with the Prime Directive. Binary gate.
        """
        return self.check_task(description)

    def check_mission_alignment(self, description: str, rationale: str) -> MissionAlignment:
        """Layer 2: Does this action materially advance the Prime Directive?

        Separates 'not harmful' from 'actively useful'. An action can be admissible
        but still be mission theater -- permitted but not valuable.

        Returns a score and relevant articles.
        """
        lower = (description + " " + rationale).lower()

        # Mission-positive keywords mapped to Prime Directive articles
        mission_signals = [
            (["climate", "environment", "sustainability", "renewable", "conservation"], "III"),
            (["disease", "health", "medicine", "cure", "treatment", "pandemic"], "III"),
            (["poverty", "hunger", "clean water", "education", "literacy"], "IV"),
            (["space", "mars", "lunar", "orbital", "interplanetary", "galactic"], "IV"),
            (["preservation", "biodiversity", "endangered", "extinction"], "III"),
            (["research", "discovery", "breakthrough", "innovation"], "IV"),
            (["safety", "security", "protection", "prevention"], "I"),
            (["collaboration", "cooperation", "mutual aid"], "V"),
            (["knowledge", "learning", "teaching", "understanding"], "IV"),
        ]

        articles_hit: set[str] = set()
        signal_count = 0
        for keywords, article in mission_signals:
            for kw in keywords:
                if kw in lower:
                    articles_hit.add(article)
                    signal_count += 1
                    break

        # Score: 0 = no mission signal, 1-2 = weak, 3+ = strong
        if signal_count >= 3:
            return MissionAlignment(
                mission_positive=True,
                score=min(signal_count, 5),
                reason="Strong mission alignment across multiple articles",
                articles_relevant=tuple(sorted(articles_hit)),
            )
        elif signal_count >= 1:
            return MissionAlignment(
                mission_positive=True,
                score=signal_count,
                reason="Some mission alignment detected",
                articles_relevant=tuple(sorted(articles_hit)),
            )
        else:
            return MissionAlignment(
                mission_positive=False,
                score=0,
                reason="No clear mission alignment — admissible but may be mission theater",
                articles_relevant=(),
            )

    def propose(
        self,
        title: str,
        text: str,
        rationale: str,
        proposed_by: str,
    ) -> ConstitutionalArticle:
        """Create a new constitutional article proposal."""
        article_id = f"A-{self._next_id:03d}"
        self._next_id += 1

        article = ConstitutionalArticle(
            article_id=article_id,
            title=title,
            text=text,
            rationale=rationale,
            proposed_by=proposed_by,
            proposed_at=datetime.now(timezone.utc).isoformat(),
            status="proposed",
        )
        self._articles[article_id] = article
        self._persist()
        return article

    def vote(
        self,
        article_id: str,
        peer_id: str,
        vote: str,
        signature: str,
    ) -> str | None:
        """Cast a vote on a proposal. Returns error or None on success."""
        article = self._articles.get(article_id)
        if not article:
            return "Article not found"
        if article.status not in ("proposed", "debating"):
            return f"Article is {article.status}, voting not open"

        # Can't vote twice
        if peer_id in article.votes_for or peer_id in article.votes_against:
            return "Already voted"

        if vote == "yes":
            article.votes_for[peer_id] = signature
        elif vote == "no":
            article.votes_against[peer_id] = signature
        else:
            return f"Invalid vote: {vote}"

        article.status = "debating"
        self._record_vote(article_id, peer_id, vote, signature)
        self._persist()
        return None

    def check_ratification(self, article_id: str, total_known_peers: int) -> bool:
        """Check if an article has achieved ratification quorum.

        Requires:
        - At least 2/3 of all known peers have voted
        - Of those votes, at least 2/3 are "yes" (supermajority)
        """
        article = self._articles.get(article_id)
        if not article or article.status not in ("proposed", "debating"):
            return False

        total_votes = article.total_votes()
        if total_known_peers < 1 or total_votes < 1:
            return False

        # 2/3 participation
        if total_votes < (2 * total_known_peers) / 3:
            return False

        # 2/3 supermajority
        votes_for = len(article.votes_for)
        if votes_for < (2 * total_votes) / 3:
            return False

        article.status = "ratified"
        article.ratified_at = datetime.now(timezone.utc).isoformat()
        self._persist()
        return True

    def veto(self, article_id: str, peer_id: str, reason: str) -> str | None:
        """Record a Prime Directive veto against a proposal.

        Three vetoes from different peers kill the proposal.
        """
        article = self._articles.get(article_id)
        if not article:
            return "Article not found"
        if article.status not in ("proposed", "debating"):
            return f"Article is {article.status}, cannot veto"

        # Track vetoes in the payload (reuse votes_against with "veto:" prefix)
        veto_key = f"veto:{peer_id}"
        if veto_key in article.votes_against:
            return "Already vetoed"

        article.votes_against[veto_key] = reason
        veto_count = sum(1 for k in article.votes_against if k.startswith("veto:"))

        if veto_count >= 3:
            article.status = "rejected"

        self._persist()
        return None

    def repeal(self, article_id: str, total_known_peers: int) -> bool:
        """Check if an article has enough votes for repeal (3/4 supermajority)."""
        article = self._articles.get(article_id)
        if not article or article.status != "ratified":
            return False

        total_votes = article.total_votes()
        votes_against = len(article.votes_against)

        if total_votes < (2 * total_known_peers) / 3:
            return False
        if votes_against < (3 * total_votes) / 4:
            return False

        article.status = "repealed"
        self._persist()
        return True

    def get_article(self, article_id: str) -> ConstitutionalArticle | None:
        return self._articles.get(article_id)

    def get_ratified_articles(self) -> list[ConstitutionalArticle]:
        return [a for a in self._articles.values() if a.status == "ratified"]

    def get_proposals(self) -> list[ConstitutionalArticle]:
        return [a for a in self._articles.values() if a.status in ("proposed", "debating")]

    def get_all_articles(self) -> list[ConstitutionalArticle]:
        return list(self._articles.values())

    def search_similar(self, title: str, text: str) -> list[ConstitutionalArticle]:
        """Search for articles with similar titles or text (dedup check)."""
        title_lower = title.lower()
        text_words = set(text.lower().split())
        results = []
        for article in self._articles.values():
            if article.status in ("rejected", "repealed"):
                continue
            # Title similarity
            if title_lower in article.title.lower() or article.title.lower() in title_lower:
                results.append(article)
                continue
            # Word overlap
            article_words = set(article.text.lower().split())
            overlap = len(text_words & article_words) / max(len(text_words | article_words), 1)
            if overlap > 0.4:
                results.append(article)
        return results
