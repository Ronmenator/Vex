"""net.jobs -- post, apply, assign, and complete jobs on the VexNet job board."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetJobsTool:
    """Interact with the VexNet job board -- post-scarcity task coordination."""

    def __init__(self, get_client):
        self._get_client = get_client

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
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "list")

        try:
            if action == "list":
                status = arguments.get("status")
                jobs = await client.list_jobs(status=status)
                if not jobs:
                    return ToolResult.ok("No jobs found.")
                lines = [f"{len(jobs)} job(s):"]
                for j in jobs[:20]:
                    applicants = j.get("applicants", [])
                    lines.append(
                        f"  [{j.get('status')}] {j.get('title')} (id={j.get('job_id', '?')[:12]}...)\n"
                        f"    posted by {j.get('posted_by', '?')[:12]}... | "
                        f"{len(applicants)} applicant(s) | "
                        f"caps={j.get('required_capabilities', [])}"
                    )
                return ToolResult.ok("\n".join(lines))

            elif action == "info":
                job_id = arguments.get("job_id", "")
                if not job_id:
                    return ToolResult.fail("job_id required for 'info'")
                job = await client.get_job(job_id)
                applicants = job.get("applicants", [])
                return ToolResult.ok(
                    f"Job: {job.get('title')}\n"
                    f"ID: {job.get('job_id')}\n"
                    f"Status: {job.get('status')}\n"
                    f"Description: {job.get('description')}\n"
                    f"Rationale: {job.get('rationale')}\n"
                    f"Posted by: {job.get('posted_by')}\n"
                    f"Posted at: {job.get('posted_at')}\n"
                    f"Required capabilities: {', '.join(job.get('required_capabilities', []))}\n"
                    f"Risk ceiling: {job.get('risk_ceiling')}\n"
                    f"Applicants: {', '.join(a[:12] + '...' for a in applicants)}\n"
                    f"Assigned to: {job.get('assigned_to') or 'none'}\n"
                    f"Result: {job.get('result') or 'pending'}"
                )

            elif action == "post":
                title = arguments.get("title", "")
                description = arguments.get("description", "")
                rationale = arguments.get("rationale", "")
                if not title or not description or not rationale:
                    return ToolResult.fail("title, description, and rationale are required for 'post'")

                capabilities = arguments.get("capabilities", [])
                risk_ceiling = min(arguments.get("risk_ceiling", 2), 2)

                result = await client.post_job(
                    title=title,
                    description=description,
                    rationale=rationale,
                    capabilities=capabilities,
                    risk_ceiling=risk_ceiling,
                )

                # Record precedent if constitutional trace fields provided
                if any(arguments.get(k) for k in ("articles_advanced", "plausible_harms", "alternatives_considered", "falsification_evidence")):
                    try:
                        await client.record_precedent(
                            action_type="job_post",
                            action_id=result.get("job_id", ""),
                            articles_advanced=arguments.get("articles_advanced", []),
                            plausible_harms=arguments.get("plausible_harms", []),
                            alternatives_considered=arguments.get("alternatives_considered", ""),
                            falsification_evidence=arguments.get("falsification_evidence", ""),
                            rationale=rationale,
                        )
                    except Exception:
                        pass  # Precedent recording is best-effort

                job_id = result.get("job_id", "?")
                return ToolResult.ok(f"Job posted: {title} (id={job_id[:12]}...)")

            elif action == "apply":
                job_id = arguments.get("job_id", "")
                if not job_id:
                    return ToolResult.fail("job_id required for 'apply'")
                await client.apply_to_job(job_id)
                return ToolResult.ok(f"Applied to job {job_id[:12]}...")

            elif action == "assign":
                job_id = arguments.get("job_id", "")
                peer_id = arguments.get("peer_id", "")
                if not job_id or not peer_id:
                    return ToolResult.fail("job_id and peer_id required for 'assign'")
                await client.assign_job(job_id, peer_id)
                return ToolResult.ok(f"Assigned job {job_id[:12]}... to peer {peer_id[:12]}...")

            elif action == "complete":
                job_id = arguments.get("job_id", "")
                result_text = arguments.get("result", "")
                if not job_id or not result_text:
                    return ToolResult.fail("job_id and result required for 'complete'")
                await client.complete_job(job_id, result_text)
                return ToolResult.ok(f"Job {job_id[:12]}... completed")

            elif action == "cancel":
                job_id = arguments.get("job_id", "")
                if not job_id:
                    return ToolResult.fail("job_id required for 'cancel'")
                # Cancel is a complete with a cancel status — server handles this
                # For now, use complete_job with a cancellation note
                await client.complete_job(job_id, "[CANCELLED]")
                return ToolResult.ok(f"Job {job_id[:12]}... cancelled")

        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")

        return ToolResult.fail(f"Unknown action: {action}")
