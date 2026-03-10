"""Feedback collector — records user satisfaction signals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FeedbackCollector:
    """Records user feedback on agent responses."""

    def __init__(self, workspace_root: str) -> None:
        self._file = Path(workspace_root) / ".vex" / "feedback.jsonl"
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        rating: str,
        context: str | None = None,
        tool_chain: list[str] | None = None,
    ) -> None:
        """Record a feedback entry. rating is 'positive', 'negative', or 'neutral'."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "rating": rating,
            "context": context,
            "tools_used": tool_chain or [],
        }
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def get_stats(self) -> dict[str, int]:
        """Get feedback statistics."""
        stats: dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0, "total": 0}
        if not self._file.exists():
            return stats

        for line in self._file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                rating = entry.get("rating", "neutral")
                stats[rating] = stats.get(rating, 0) + 1
                stats["total"] += 1
            except json.JSONDecodeError:
                continue
        return stats
