"""net.peers -- list and manage VexNet peers."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetPeersTool:
    """List and manage peers on VexNet."""

    def __init__(self, get_node):
        self._get_node = get_node

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.peers",
            description="List, trust, or block VexNet peers.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "info", "trust", "block"],
                        "description": "Action to perform.",
                        "default": "list",
                    },
                    "peer_id": {
                        "type": "string",
                        "description": "Peer ID (required for info/trust/block).",
                    },
                    "trust_level": {
                        "type": "integer",
                        "description": "Trust level to set (0=deny, 1=read-only, 2=read+write). For 'trust' action.",
                    },
                },
            },
            risk_tier=RiskTier.READ_ONLY,
            group="net",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        node = self._get_node()
        if not node or not node.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "list")

        if action == "list":
            connected = node.peers.get_connected()
            if not connected:
                return ToolResult.ok("No peers connected.")
            lines = [f"{len(connected)} connected peer(s):"]
            for state in connected:
                i = state.identity
                lines.append(
                    f"  {i.display_name} ({i.peer_id[:12]}...) "
                    f"caps=[{', '.join(i.capabilities)}] "
                    f"since={state.connected_at}"
                )
            return ToolResult.ok("\n".join(lines))

        elif action == "info":
            peer_id = arguments.get("peer_id", "")
            if not peer_id:
                return ToolResult.fail("peer_id required for 'info'")
            state = node.peers.get(peer_id)
            if not state:
                return ToolResult.fail(f"Peer {peer_id[:12]}... not connected")
            i = state.identity
            policy = node.permissions.get_policy(peer_id)
            return ToolResult.ok(
                f"Peer: {i.display_name}\n"
                f"ID: {i.peer_id}\n"
                f"Capabilities: {', '.join(i.capabilities)}\n"
                f"Endpoint: {i.endpoint}\n"
                f"Connected since: {state.connected_at}\n"
                f"Trust level: {policy.trust_level}\n"
                f"Risk ceiling: {policy.max_risk_tier.name}\n"
                f"Rate limit: {policy.rate_limit}/hour"
            )

        elif action in ("trust", "block"):
            peer_id = arguments.get("peer_id", "")
            if not peer_id:
                return ToolResult.fail(f"peer_id required for '{action}'")

            from vex.network.permissions import PeerPolicy

            if action == "block":
                node.permissions.set_policy(PeerPolicy(peer_id=peer_id, trust_level=0))
                return ToolResult.ok(f"Blocked peer {peer_id[:12]}...")
            else:
                trust = arguments.get("trust_level", 2)
                node.permissions.set_policy(PeerPolicy(peer_id=peer_id, trust_level=trust))
                return ToolResult.ok(f"Set trust level {trust} for peer {peer_id[:12]}...")

        return ToolResult.fail(f"Unknown action: {action}")
