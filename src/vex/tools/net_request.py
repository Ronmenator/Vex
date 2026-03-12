"""net.request -- delegate a task directly to a specific VexNet peer.

In the centralized architecture, direct peer-to-peer requests go through the
job board. This tool posts a targeted job and pre-assigns it to the specified peer.
"""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetRequestTool:
    """Delegate a task to a specific peer on VexNet via the job board."""

    def __init__(self, get_client):
        self._get_client = get_client

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.request",
            description="Send a task directly to a specific VexNet peer. Use net.jobs for open collaboration instead.",
            parameters={
                "type": "object",
                "properties": {
                    "peer_id": {
                        "type": "string",
                        "description": "The peer_id to send the task to.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Full description of the task.",
                    },
                    "risk_ceiling": {
                        "type": "integer",
                        "description": "Max risk tier (0=read-only, 1=write-local, 2=write-external). Default 2.",
                        "default": 2,
                    },
                },
                "required": ["peer_id", "description"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="net",
            timeout=300,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        peer_id = arguments["peer_id"]
        description = arguments["description"]
        risk_ceiling = min(arguments.get("risk_ceiling", 2), 2)

        try:
            # Post a job and immediately assign to the target peer
            result = await client.post_job(
                title=f"Direct request to {peer_id}",
                description=description,
                rationale="Direct peer-to-peer task delegation",
                capabilities=[],
                risk_ceiling=risk_ceiling,
            )
            job_id = result.get("job_id", "")

            if job_id:
                await client.assign_job(job_id, peer_id)

            return ToolResult.ok(
                f"Task sent to peer {peer_id} (job_id={job_id})\n"
                f"Awaiting response..."
            )
        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")
