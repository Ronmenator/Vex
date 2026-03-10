"""Policy engine — autonomy-based graduated trust."""

from __future__ import annotations

from enum import Enum

from vex.agent.definition import AgentDefinition
from vex.tools.base import RiskTier, ToolSchema


class PolicyDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRES_APPROVAL = "requires_approval"


class PolicyEngine:
    """Evaluates whether a tool call should be allowed, denied, or require approval.

    Uses autonomy levels instead of role-based capabilities:
    - Level 0: Everything requires approval
    - Level 1: Read + write-local auto-approved; external/destructive need approval
    - Level 2: Only destructive requires approval
    - Level 3: Full autonomy, no approval prompts
    """

    def __init__(
        self,
        global_deny: list[str] | None = None,
        global_allow: list[str] | None = None,
    ) -> None:
        self._global_deny = global_deny or []
        self._global_allow = global_allow or []

    def evaluate(
        self, schema: ToolSchema, agent_def: AgentDefinition
    ) -> PolicyDecision:
        """Evaluate whether a tool call should proceed."""
        # 1. Global deny list (always wins)
        if self._in_list(self._global_deny, schema.name, schema.group):
            return PolicyDecision.DENY

        # 2. Agent-specific deny
        if self._in_list(agent_def.tool_deny, schema.name, schema.group):
            return PolicyDecision.DENY

        # 3. Agent-specific allow (if non-empty, tool must be in it)
        if agent_def.tool_allow and not self._in_list(
            agent_def.tool_allow, schema.name, schema.group
        ):
            return PolicyDecision.DENY

        # 4. Autonomy-adjusted approval threshold
        threshold = self._approval_threshold(agent_def.autonomy_level)
        if schema.risk_tier >= threshold:
            return PolicyDecision.REQUIRES_APPROVAL

        return PolicyDecision.ALLOW

    def _approval_threshold(self, autonomy_level: int) -> RiskTier:
        """Map autonomy level to the risk tier that triggers approval."""
        if autonomy_level >= 3:
            return RiskTier(99)  # Nothing triggers approval
        if autonomy_level == 2:
            return RiskTier.DESTRUCTIVE
        if autonomy_level == 1:
            return RiskTier.WRITE_EXTERNAL
        # Level 0: everything needs approval
        return RiskTier.READ_ONLY

    def _in_list(self, lst: list[str], name: str, group: str) -> bool:
        """Check if a tool name or group is in a list."""
        return name in lst or group in lst
