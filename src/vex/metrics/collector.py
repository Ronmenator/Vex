"""Metrics collector — tracks tool execution performance."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ToolMetric:
    """A single tool execution metric."""

    tool_name: str
    agent_id: str
    success: bool
    duration_s: float
    error_type: str | None = None
    timestamp: str = ""
    retries: int = 0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class MetricsCollector:
    """Collects and persists tool execution metrics."""

    def __init__(self, workspace_root: str) -> None:
        self._dir = Path(workspace_root) / ".vex" / "metrics"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._session_metrics: list[ToolMetric] = []

    def record(self, metric: ToolMetric) -> None:
        """Record a tool execution metric."""
        self._session_metrics.append(metric)
        self._persist(metric)

    def get_session_metrics(self) -> list[ToolMetric]:
        """Get all metrics for the current session."""
        return list(self._session_metrics)

    def get_tool_stats(self, tool_name: str | None = None) -> dict[str, Any]:
        """Get aggregated stats, optionally filtered by tool name."""
        metrics = self._load_all()
        if tool_name:
            metrics = [m for m in metrics if m["tool_name"] == tool_name]

        if not metrics:
            return {"total": 0}

        successes = sum(1 for m in metrics if m.get("success"))
        total = len(metrics)
        durations = [m.get("duration_s", 0) for m in metrics]

        return {
            "total": total,
            "success_rate": round(successes / total, 3) if total else 0,
            "avg_duration_s": round(sum(durations) / len(durations), 3),
            "max_duration_s": round(max(durations), 3),
            "error_count": total - successes,
        }

    def get_common_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get most common error patterns."""
        metrics = self._load_all()
        error_counts: dict[str, int] = {}
        for m in metrics:
            if not m.get("success") and m.get("error_type"):
                key = f"{m['tool_name']}:{m['error_type']}"
                error_counts[key] = error_counts.get(key, 0) + 1

        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        return [
            {"pattern": k, "count": v}
            for k, v in sorted_errors[:limit]
        ]

    def get_tool_reliability(self, tool_name: str) -> float:
        """Get success rate for a specific tool (0.0 to 1.0)."""
        stats = self.get_tool_stats(tool_name)
        return stats.get("success_rate", 0.0)

    def _persist(self, metric: ToolMetric) -> None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = self._dir / f"metrics_{date}.jsonl"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(metric.__dict__) + "\n")

    def _load_all(self) -> list[dict[str, Any]]:
        """Load all historical metrics."""
        results: list[dict[str, Any]] = []
        for filepath in sorted(self._dir.glob("metrics_*.jsonl")):
            for line in filepath.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return results
