"""net.request -- delegate a task directly to a specific VexNet peer."""

from __future__ import annotations

import asyncio
from typing import Any

from vex.network.protocol import Envelope, MessageType
from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetRequestTool:
    """Delegate a task to a specific peer on VexNet."""

    def __init__(self, get_node):
        self._get_node = get_node

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
        node = self._get_node()
        if not node or not node.enabled:
            return ToolResult.fail("VexNet is not enabled")

        peer_id = arguments["peer_id"]
        description = arguments["description"]
        risk_ceiling = min(arguments.get("risk_ceiling", 2), 2)

        state = node.peers.get(peer_id)
        if not state:
            return ToolResult.fail(f"Peer {peer_id[:12]}... is not connected")

        envelope = Envelope.create(
            MessageType.TASK_REQUEST,
            node.identity.peer_id,
            {
                "description": description,
                "risk_ceiling": risk_ceiling,
            },
            node.keypair,
            recipient_id=peer_id,
        )

        sent = await node.peers.send_to(peer_id, envelope)
        if not sent:
            return ToolResult.fail("Failed to send task request")

        return ToolResult.ok(
            f"Task request sent to {state.identity.display_name} ({peer_id[:12]}...)\n"
            f"Awaiting response..."
        )
