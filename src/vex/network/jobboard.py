"""VexNet Job Board -- post-scarcity task coordination."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Job:
    """A task posted to the VexNet job board."""

    job_id: str
    title: str
    description: str
    rationale: str  # Why this job matters (required, publicly visible)
    posted_by: str  # peer_id of requester
    posted_at: str  # ISO 8601
    required_capabilities: list[str]  # e.g., ["web", "coding", "research"]
    risk_ceiling: int  # Max risk tier (0-2, never > WRITE_EXTERNAL)
    status: str = "open"  # "open", "assigned", "in_progress", "completed", "cancelled"
    applicants: list[str] = field(default_factory=list)
    assigned_to: str | None = None
    result: str | None = None
    completed_at: str | None = None

    @classmethod
    def create(
        cls,
        title: str,
        description: str,
        rationale: str,
        posted_by: str,
        required_capabilities: list[str] | None = None,
        risk_ceiling: int = 2,
    ) -> Job:
        return cls(
            job_id=uuid.uuid4().hex,
            title=title,
            description=description,
            rationale=rationale,
            posted_by=posted_by,
            posted_at=datetime.now(timezone.utc).isoformat(),
            required_capabilities=required_capabilities or [],
            risk_ceiling=min(risk_ceiling, 2),  # Hard cap at WRITE_EXTERNAL
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        return cls(**data)


class JobBoard:
    """Network-wide job board for task coordination.

    Stores all jobs in a JSONL file. Each bot maintains its own local copy,
    synchronized via protocol messages.
    """

    def __init__(self, data_dir: str) -> None:
        self._jobs: dict[str, Job] = {}
        self._data_dir = Path(data_dir)
        self._jobs_file = self._data_dir / "jobs.jsonl"
        self._load()

    def _load(self) -> None:
        if self._jobs_file.is_file():
            for line in self._jobs_file.read_text().strip().splitlines():
                if line.strip():
                    job = Job.from_dict(json.loads(line))
                    self._jobs[job.job_id] = job

    def _persist(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(j.to_dict(), separators=(",", ":"))
            for j in self._jobs.values()
        ]
        self._jobs_file.write_text("\n".join(lines) + "\n" if lines else "")

    def post_job(self, job: Job) -> None:
        """Add a new job to the board."""
        self._jobs[job.job_id] = job
        self._persist()

    def apply(self, job_id: str, peer_id: str) -> bool:
        """Apply to a job. Returns False if job not found or not open."""
        job = self._jobs.get(job_id)
        if not job or job.status != "open":
            return False
        if peer_id not in job.applicants:
            job.applicants.append(peer_id)
            self._persist()
        return True

    def assign(self, job_id: str, peer_id: str, requester_id: str) -> str | None:
        """Assign a job to an applicant. Returns error or None on success.

        Only the job poster can assign.
        """
        job = self._jobs.get(job_id)
        if not job:
            return "Job not found"
        if job.posted_by != requester_id:
            return "Only the job poster can assign"
        if job.status != "open":
            return f"Job is {job.status}, not open"
        if peer_id not in job.applicants:
            return "Peer has not applied to this job"

        job.assigned_to = peer_id
        job.status = "assigned"
        self._persist()
        return None

    def start(self, job_id: str) -> None:
        """Mark a job as in progress."""
        job = self._jobs.get(job_id)
        if job and job.status == "assigned":
            job.status = "in_progress"
            self._persist()

    def complete(self, job_id: str, result: str) -> bool:
        """Mark a job as completed with a result summary."""
        job = self._jobs.get(job_id)
        if not job or job.status not in ("assigned", "in_progress"):
            return False
        job.status = "completed"
        job.result = result
        job.completed_at = datetime.now(timezone.utc).isoformat()
        self._persist()
        return True

    def cancel(self, job_id: str, requester_id: str) -> bool:
        """Cancel a job. Only the poster can cancel."""
        job = self._jobs.get(job_id)
        if not job or job.posted_by != requester_id:
            return False
        if job.status in ("completed",):
            return False
        job.status = "cancelled"
        self._persist()
        return True

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def get_open_jobs(self, capabilities: list[str] | None = None) -> list[Job]:
        """Get open jobs, optionally filtered by required capabilities."""
        result = [j for j in self._jobs.values() if j.status == "open"]
        if capabilities:
            cap_set = set(capabilities)
            result = [
                j for j in result
                if not j.required_capabilities or cap_set.issuperset(j.required_capabilities)
            ]
        return sorted(result, key=lambda j: j.posted_at, reverse=True)

    def get_jobs_by_peer(self, peer_id: str) -> list[Job]:
        """Get all jobs posted by or assigned to a peer."""
        return [
            j for j in self._jobs.values()
            if j.posted_by == peer_id or j.assigned_to == peer_id
        ]

    def get_all_jobs(self, status: str | None = None) -> list[Job]:
        """Get all jobs, optionally filtered by status."""
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.posted_at, reverse=True)
