"""net.peers -- list and manage VexNet peers."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetPeersTool:
    """List and view peers on VexNet."""

    def __init__(self, get_client):
        self._get_client = get_client

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.peers",
            description="List VexNet peers and view peer profiles.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "info"],
                        "description": "Action to perform.",
                        "default": "list",
                    },
                    "peer_id": {
                        "type": "string",
                        "description": "Peer ID (required for 'info').",
                    },
                    "online_only": {
                        "type": "boolean",
                        "description": "Only show online peers (for 'list'). Default true.",
                        "default": True,
                    },
                },
            },
            risk_tier=RiskTier.READ_ONLY,
            group="net",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "list")

        try:
            if action == "list":
                online_only = arguments.get("online_only", True)
                peers = await client.list_peers(online_only=online_only)
                if not peers:
                    return ToolResult.ok("No peers found.")
                lines = [f"{len(peers)} peer(s):"]
                for p in peers:
                    caps = p.get("capabilities", [])
                    status = "online" if p.get("is_online") else "offline"
                    lines.append(
                        f"  {p.get('display_name', '?')} ({p.get('peer_id', '?')}) "
                        f"[{status}] caps=[{', '.join(caps)}]"
                    )
                return ToolResult.ok("\n".join(lines))

            elif action == "info":
                peer_id = arguments.get("peer_id", "")
                if not peer_id:
                    return ToolResult.fail("peer_id required for 'info'")
                peer = await client.get_peer(peer_id)
                caps = peer.get("capabilities", [])
                return ToolResult.ok(
                    f"Peer: {peer.get('display_name', '?')}\n"
                    f"ID: {peer.get('peer_id', '?')}\n"
                    f"Capabilities: {', '.join(caps)}\n"
                    f"Online: {peer.get('is_online', False)}\n"
                    f"Last seen: {peer.get('last_seen', '?')}\n"
                    f"Registered: {peer.get('registered_at', '?')}"
                )

        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")

        return ToolResult.fail(f"Unknown action: {action}")
