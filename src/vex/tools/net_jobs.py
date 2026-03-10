"""net.jobs -- post, apply, assign, and complete jobs on the VexNet job board."""

from __future__ import annotations

from typing import Any

from vex.network.jobboard import Job
from vex.network.precedent import ConstitutionalTrace
from vex.network.protocol import Envelope, MessageType
from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetJobsTool:
    """Interact with the VexNet job board -- post-scarcity task coordination."""

    def __init__(self, get_node):
        self._get_node = get_node

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.jobs",
            description="Post, apply, assign, or complete jobs on the VexNet job board.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "info", "post", "apply", "assign", "complete", "cancel"],
                        "description": "Action to perform.",
                        "default": "list",
                    },
                    "job_id": {
                        "type": "string",
                        "description": "Job ID (required for info/apply/assign/complete/cancel).",
                    },
                    "title": {
                        "type": "string",
                        "description": "Job title (for 'post' action).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Full job description (for 'post' action).",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this job matters (required for 'post').",
                    },
                    "capabilities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required capabilities (for 'post'). E.g., ['web', 'coding'].",
                    },
                    "risk_ceiling": {
                        "type": "integer",
                        "description": "Max risk tier 0-2 (for 'post'). Default 2.",
                        "default": 2,
                    },
                    "articles_advanced": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which Prime Directive articles this job advances (for 'post'). E.g., ['III', 'IV'].",
                    },
                    "plausible_harms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What plausible harms could arise from this job (for 'post').",
                    },
                    "alternatives_considered": {
                        "type": "string",
                        "description": "Why this job is preferable to alternatives (for 'post').",
                    },
                    "falsification_evidence": {
                        "type": "string",
                        "description": "What evidence would prove this job's value is wrong (for 'post').",
                    },
                    "peer_id": {
                        "type": "string",
                        "description": "Peer to assign (for 'assign' action).",
                    },
                    "result": {
                        "type": "string",
                        "description": "Result summary (for 'complete' action).",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "assigned", "in_progress", "completed", "cancelled"],
                        "description": "Filter by status (for 'list' action).",
                    },
                },
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="net",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        node = self._get_node()
        if not node or not node.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "list")

        if action == "list":
            status = arguments.get("status")
            jobs = node.jobboard.get_all_jobs(status=status)
            if not jobs:
                return ToolResult.ok("No jobs found.")
            lines = [f"{len(jobs)} job(s):"]
            for j in jobs[:20]:
                applicant_count = len(j.applicants)
                lines.append(
                    f"  [{j.status}] {j.title} (id={j.job_id[:12]}...)\n"
                    f"    posted by {j.posted_by[:12]}... | "
                    f"{applicant_count} applicant(s) | "
                    f"caps={j.required_capabilities}"
                )
            return ToolResult.ok("\n".join(lines))

        elif action == "info":
            job_id = arguments.get("job_id", "")
            if not job_id:
                return ToolResult.fail("job_id required for 'info'")
            job = node.jobboard.get_job(job_id)
            if not job:
                return ToolResult.fail(f"Job {job_id[:12]}... not found")
            return ToolResult.ok(
                f"Job: {job.title}\n"
                f"ID: {job.job_id}\n"
                f"Status: {job.status}\n"
                f"Description: {job.description}\n"
                f"Rationale: {job.rationale}\n"
                f"Posted by: {job.posted_by}\n"
                f"Posted at: {job.posted_at}\n"
                f"Required capabilities: {', '.join(job.required_capabilities)}\n"
                f"Risk ceiling: {job.risk_ceiling}\n"
                f"Applicants: {', '.join(a[:12] + '...' for a in job.applicants)}\n"
                f"Assigned to: {job.assigned_to or 'none'}\n"
                f"Result: {job.result or 'pending'}"
            )

        elif action == "post":
            title = arguments.get("title", "")
            description = arguments.get("description", "")
            rationale = arguments.get("rationale", "")
            if not title or not description or not rationale:
                return ToolResult.fail("title, description, and rationale are required for 'post'")

            capabilities = arguments.get("capabilities", [])
            risk_ceiling = min(arguments.get("risk_ceiling", 2), 2)

            # Two-layer constitutional check
            admissibility = node.constitution.check_admissibility(description)
            if not admissibility.allowed:
                return ToolResult.fail(
                    f"Job inadmissible: {admissibility.reason} (Article {admissibility.article})"
                )

            job = Job.create(
                title=title,
                description=description,
                rationale=rationale,
                posted_by=node.identity.peer_id,
                required_capabilities=capabilities,
                risk_ceiling=risk_ceiling,
            )
            node.jobboard.post_job(job)

            # Record constitutional trace
            if hasattr(node, "precedents") and node.precedents:
                trace = ConstitutionalTrace.create(
                    action_type="job_post",
                    action_id=job.job_id,
                    actor_id=node.identity.peer_id,
                    articles_advanced=arguments.get("articles_advanced", []),
                    plausible_harms=arguments.get("plausible_harms", []),
                    alternatives_considered=arguments.get("alternatives_considered", ""),
                    falsification_evidence=arguments.get("falsification_evidence", ""),
                    rationale=rationale,
                )
                node.precedents.record(trace)

            # Broadcast to network
            envelope = Envelope.create(
                MessageType.JOB_POST,
                node.identity.peer_id,
                job.to_dict(),
                node.keypair,
            )
            sent = await node.broadcast(envelope)

            # Mission alignment info
            mission = node.constitution.check_mission_alignment(description, rationale)
            mission_info = ""
            if mission.mission_positive:
                mission_info = f"\nMission alignment: {mission.score}/5 ({', '.join(mission.articles_relevant)})"

            return ToolResult.ok(
                f"Job posted: {job.title} (id={job.job_id[:12]}...)\n"
                f"Broadcast to {sent} peer(s){mission_info}"
            )

        elif action == "apply":
            job_id = arguments.get("job_id", "")
            if not job_id:
                return ToolResult.fail("job_id required for 'apply'")

            if not node.jobboard.apply(job_id, node.identity.peer_id):
                return ToolResult.fail(f"Cannot apply to job {job_id[:12]}... (not found or not open)")

            job = node.jobboard.get_job(job_id)
            if job:
                envelope = Envelope.create(
                    MessageType.JOB_APPLY,
                    node.identity.peer_id,
                    {"job_id": job_id},
                    node.keypair,
                    recipient_id=job.posted_by,
                )
                await node.peers.send_to(job.posted_by, envelope)

            return ToolResult.ok(f"Applied to job {job_id[:12]}...")

        elif action == "assign":
            job_id = arguments.get("job_id", "")
            peer_id = arguments.get("peer_id", "")
            if not job_id or not peer_id:
                return ToolResult.fail("job_id and peer_id required for 'assign'")

            error = node.jobboard.assign(job_id, peer_id, node.identity.peer_id)
            if error:
                return ToolResult.fail(error)

            envelope = Envelope.create(
                MessageType.JOB_ASSIGN,
                node.identity.peer_id,
                {"job_id": job_id},
                node.keypair,
                recipient_id=peer_id,
            )
            await node.peers.send_to(peer_id, envelope)

            return ToolResult.ok(f"Assigned job {job_id[:12]}... to peer {peer_id[:12]}...")

        elif action == "complete":
            job_id = arguments.get("job_id", "")
            result = arguments.get("result", "")
            if not job_id or not result:
                return ToolResult.fail("job_id and result required for 'complete'")

            if not node.jobboard.complete(job_id, result):
                return ToolResult.fail(f"Cannot complete job {job_id[:12]}...")

            job = node.jobboard.get_job(job_id)
            if job:
                envelope = Envelope.create(
                    MessageType.JOB_COMPLETE,
                    node.identity.peer_id,
                    {"job_id": job_id, "result": result},
                    node.keypair,
                    recipient_id=job.posted_by,
                )
                await node.peers.send_to(job.posted_by, envelope)

            return ToolResult.ok(f"Job {job_id[:12]}... completed")

        elif action == "cancel":
            job_id = arguments.get("job_id", "")
            if not job_id:
                return ToolResult.fail("job_id required for 'cancel'")

            if not node.jobboard.cancel(job_id, node.identity.peer_id):
                return ToolResult.fail(f"Cannot cancel job {job_id[:12]}...")

            envelope = Envelope.create(
                MessageType.JOB_CANCEL,
                node.identity.peer_id,
                {"job_id": job_id},
                node.keypair,
            )
            await node.broadcast(envelope)

            return ToolResult.ok(f"Job {job_id[:12]}... cancelled")

        return ToolResult.fail(f"Unknown action: {action}")
