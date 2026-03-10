"""net.discover -- find VexNet peers by capability."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetDiscoverTool:
    """Find peers on VexNet by capability."""

    def __init__(self, get_node):
        self._get_node = get_node

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.discover",
            description="Find VexNet peers by capability. Lists connected peers, optionally filtered.",
            parameters={
                "type": "object",
                "properties": {
                    "capability": {
                        "type": "string",
                        "description": "Filter by capability (e.g., 'web', 'coding', 'research'). Omit for all peers.",
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

        capability = arguments.get("capability")

        if capability:
            peers = node.peers.find_by_capability(capability)
        else:
            peers = node.peers.get_connected()

        if not peers:
            return ToolResult.ok("No peers found" + (f" with capability '{capability}'" if capability else ""))

        lines = [f"Found {len(peers)} peer(s):"]
        for state in peers:
            identity = state.identity
            lines.append(
                f"  - {identity.display_name} ({identity.peer_id[:12]}...)"
                f"  capabilities: {', '.join(identity.capabilities)}"
                f"  endpoint: {identity.endpoint}"
            )
        return ToolResult.ok("\n".join(lines))
