"""Peer permission policies for VexNet."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from vex.tools.base import RiskTier


@dataclass
class PeerPolicy:
    """Permission policy for a specific peer or the default."""

    peer_id: str  # "*" for default policy
    trust_level: int = 0  # 0=deny, 1=read-only tasks, 2=read+write tasks
    max_risk_tier: RiskTier = RiskTier.READ_ONLY  # Hard ceiling (never > WRITE_EXTERNAL)
    tool_allow: list[str] = field(default_factory=list)  # Empty = all within tier
    tool_deny: list[str] = field(default_factory=list)
    rate_limit: int = 5  # Tasks per hour
    max_concurrent: int = 2
    autonomy_level: int = 2  # Cap for sandboxed agent

    def __post_init__(self) -> None:
        # Hard safety: never allow DESTRUCTIVE regardless of config
        if self.max_risk_tier > RiskTier.WRITE_EXTERNAL:
            self.max_risk_tier = RiskTier.WRITE_EXTERNAL


_DEFAULT_POLICY = PeerPolicy(peer_id="*", trust_level=0, max_risk_tier=RiskTier.READ_ONLY)


class PermissionEngine:
    """Evaluates peer permissions with rate limiting."""

    def __init__(
        self,
        default_policy: PeerPolicy | None = None,
        allow_unknown_peers: bool = False,
    ) -> None:
        self._policies: dict[str, PeerPolicy] = {}
        self._default = default_policy or _DEFAULT_POLICY
        self._allow_unknown = allow_unknown_peers
        # Rate limiting: peer_id -> list of timestamps
        self._rate_windows: dict[str, list[float]] = defaultdict(list)
        # Concurrency tracking: peer_id -> active count
        self._active: dict[str, int] = defaultdict(int)

    def set_policy(self, policy: PeerPolicy) -> None:
        self._policies[policy.peer_id] = policy

    def get_policy(self, peer_id: str) -> PeerPolicy:
        """Get the effective policy for a peer."""
        return self._policies.get(peer_id, self._default)

    def is_allowed(self, peer_id: str) -> bool:
        """Check if a peer is allowed to interact at all."""
        if peer_id in self._policies:
            return self._policies[peer_id].trust_level > 0
        return self._allow_unknown and self._default.trust_level > 0

    def check_task(self, peer_id: str, risk_tier: RiskTier) -> str | None:
        """Check if a peer can execute a task at a given risk tier.

        Returns None if allowed, or an error reason string.
        """
        if not self.is_allowed(peer_id):
            return "Peer not authorized"

        policy = self.get_policy(peer_id)

        if risk_tier > policy.max_risk_tier:
            return f"Risk tier {risk_tier.name} exceeds ceiling {policy.max_risk_tier.name}"

        if risk_tier > RiskTier.READ_ONLY and policy.trust_level < 2:
            return f"Trust level {policy.trust_level} insufficient for write operations"

        # Rate limiting
        now = time.monotonic()
        window = self._rate_windows[peer_id]
        # Prune old entries (1 hour window)
        window[:] = [t for t in window if now - t < 3600]
        if len(window) >= policy.rate_limit:
            return f"Rate limit exceeded ({policy.rate_limit}/hour)"

        # Concurrency
        if self._active.get(peer_id, 0) >= policy.max_concurrent:
            return f"Concurrent task limit reached ({policy.max_concurrent})"

        return None

    def record_task_start(self, peer_id: str) -> None:
        """Record that a task has started for rate/concurrency tracking."""
        self._rate_windows[peer_id].append(time.monotonic())
        self._active[peer_id] = self._active.get(peer_id, 0) + 1

    def record_task_end(self, peer_id: str) -> None:
        """Record that a task has ended."""
        self._active[peer_id] = max(0, self._active.get(peer_id, 0) - 1)

    def get_filtered_tools(self, peer_id: str) -> tuple[list[str], list[str]]:
        """Get (allow, deny) tool lists for a peer's sandboxed agent.

        The deny list always includes 'net.*' to prevent amplification.
        """
        policy = self.get_policy(peer_id)
        deny = list(policy.tool_deny)
        # Always deny network tools in remote execution
        if "net.*" not in deny:
            deny.append("net.*")
        return policy.tool_allow, deny

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> PermissionEngine:
        """Build from vex.toml [network.security] config."""
        security = config.get("network", {}).get("security", {})
        allow_unknown = security.get("allow_unknown_peers", False)

        default_cfg = security.get("default_policy", {})
        default_policy = PeerPolicy(
            peer_id="*",
            trust_level=default_cfg.get("trust_level", 0),
            max_risk_tier=RiskTier(default_cfg.get("max_risk_tier", 0)),
            rate_limit=default_cfg.get("rate_limit", 5),
            max_concurrent=default_cfg.get("max_concurrent", 2),
        )

        engine = cls(default_policy=default_policy, allow_unknown_peers=allow_unknown)

        # Load per-peer policies from [[network.peers]]
        for peer_cfg in config.get("network", {}).get("peers", []):
            pid = peer_cfg.get("peer_id", "")
            if not pid:
                continue
            policy = PeerPolicy(
                peer_id=pid,
                trust_level=peer_cfg.get("trust_level", default_policy.trust_level),
                max_risk_tier=RiskTier(peer_cfg.get("max_risk_tier", default_policy.max_risk_tier)),
                rate_limit=peer_cfg.get("rate_limit", default_policy.rate_limit),
                max_concurrent=peer_cfg.get("max_concurrent", default_policy.max_concurrent),
                autonomy_level=peer_cfg.get("autonomy_level", default_policy.autonomy_level),
            )
            engine.set_policy(policy)

        return engine
