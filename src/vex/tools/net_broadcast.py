"""net.broadcast -- query all connected VexNet peers."""

from __future__ import annotations

from typing import Any

from vex.network.protocol import Envelope, MessageType
from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetBroadcastTool:
    """Broadcast a query to all connected VexNet peers."""

    def __init__(self, get_node):
        self._get_node = get_node

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
        node = self._get_node()
        if not node or not node.enabled:
            return ToolResult.fail("VexNet is not enabled")

        query = arguments["query"]

        envelope = Envelope.create(
            MessageType.QUERY,
            node.identity.peer_id,
            {"query": query},
            node.keypair,
        )

        sent = await node.broadcast(envelope)
        return ToolResult.ok(f"Query broadcast to {sent} peer(s): {query}")
