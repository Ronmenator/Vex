"""net.broadcast -- post a query to all VexNet peers via the job board.

In the centralized architecture, broadcasts are implemented as open jobs
that any peer can respond to.
"""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetBroadcastTool:
    """Broadcast a query to all peers on VexNet via an open job."""

    def __init__(self, get_client):
        self._get_client = get_client

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.broadcast",
            description="Broadcast a query to all connected peers on VexNet.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query to broadcast to all peers.",
                    },
                },
                "required": ["query"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="net",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        query = arguments["query"]

        try:
            # Broadcast queries become open jobs that any peer can see and respond to
            result = await client.post_job(
                title=f"Network Query: {query[:60]}",
                description=f"Broadcast query to all peers:\n\n{query}",
                rationale="Network-wide query broadcast",
                capabilities=[],
                risk_ceiling=0,  # Read-only queries
            )
            job_id = result.get("job_id", "?")
            return ToolResult.ok(f"Query broadcast as job {job_id[:12]}...: {query}")
        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")
