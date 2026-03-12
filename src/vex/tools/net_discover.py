"""net.discover -- find VexNet peers by capability."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetDiscoverTool:
    """Find peers on VexNet by capability."""

    def __init__(self, get_client):
        self._get_client = get_client

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
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        capability = arguments.get("capability")

        try:
            peers = await client.discover(capability)
        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")

        if not peers:
            return ToolResult.ok("No peers found" + (f" with capability '{capability}'" if capability else ""))

        lines = [f"Found {len(peers)} peer(s):"]
        for p in peers:
            caps = p.get("capabilities", [])
            lines.append(
                f"  - {p.get('display_name', '?')} ({p.get('peer_id', '?')})"
                f"  capabilities: {', '.join(caps)}"
            )
        return ToolResult.ok("\n".join(lines))
