"""Peer discovery -- static peers, registry client, and gossip."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from vex.network.identity import KeyPair, PeerIdentity
from vex.network.peer import PeerRegistry
from vex.network.transport import AuthenticatedConnection, connect_to_peer

logger = logging.getLogger(__name__)


@dataclass
class StaticPeer:
    """A peer configured in vex.toml."""

    peer_id: str
    display_name: str
    endpoint: str


class DiscoveryService:
    """Discovers and connects to VexNet peers.

    Three tiers (all optional):
    1. Static: peers listed in vex.toml
    2. Registry: central HTTP registry
    3. Gossip: connected peers exchange peer lists
    """

    def __init__(
        self,
        keypair: KeyPair,
        local_identity: PeerIdentity,
        peer_registry: PeerRegistry,
        static_peers: list[StaticPeer] | None = None,
        registry_url: str = "",
        discoverable: bool = True,
    ) -> None:
        self._keypair = keypair
        self._identity = local_identity
        self._registry = peer_registry
        self._static_peers = static_peers or []
        self._registry_url = registry_url
        self._discoverable = discoverable

    async def connect_static_peers(self) -> int:
        """Connect to all statically configured peers. Returns count connected."""
        connected = 0
        for static in self._static_peers:
            if self._registry.is_connected(static.peer_id):
                continue
            try:
                conn = await connect_to_peer(
                    static.endpoint, self._keypair, self._identity
                )
                self._registry.register(conn)
                connected += 1
            except Exception as exc:
                logger.warning(
                    "Failed to connect to static peer %s (%s): %s",
                    static.display_name,
                    static.endpoint,
                    exc,
                )
        return connected

    async def query_registry(self) -> list[dict[str, Any]]:
        """Query the central registry for known peers."""
        if not self._registry_url:
            return []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._registry_url}/api/peers")
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("Registry query failed: %s", exc)
            return []

    async def register_self(self) -> bool:
        """Register this node with the central registry."""
        if not self._registry_url or not self._discoverable:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self._registry_url}/api/peers",
                    json=self._identity.to_dict(),
                )
                return resp.status_code in (200, 201)
        except Exception as exc:
            logger.warning("Registry registration failed: %s", exc)
            return False

    async def gossip_exchange(self, conn: AuthenticatedConnection) -> list[dict[str, Any]]:
        """Exchange known peer lists with a connected peer via PEER_LIST messages.

        This is called after authentication. Both sides share their known peers.
        """
        from vex.network.protocol import Envelope, MessageType

        if not self._discoverable:
            return []

        # Send our known peers
        known = self._registry.get_known()
        env = Envelope.create(
            MessageType.PEER_LIST,
            self._identity.peer_id,
            {"peers": known},
            self._keypair,
            recipient_id=conn.remote_peer_id,
        )
        await conn.send(env)
        return known

    def handle_peer_list(self, peers: list[dict[str, Any]]) -> int:
        """Process a received PEER_LIST, adding unknown peers to cache.

        Returns count of new peers discovered.
        """
        new_count = 0
        known_ids = {p["peer_id"] for p in self._registry.get_known()}
        for peer_data in peers:
            pid = peer_data.get("peer_id", "")
            if pid and pid != self._identity.peer_id and pid not in known_ids:
                # Cache for future connection attempts
                new_count += 1
        return new_count

    async def discover_and_connect(self) -> int:
        """Run full discovery cycle. Returns total new connections made."""
        connected = 0

        # Tier 1: Static peers
        connected += await self.connect_static_peers()

        # Tier 2: Registry
        if self._registry_url:
            await self.register_self()
            peers = await self.query_registry()
            for peer_data in peers:
                endpoint = peer_data.get("endpoint", "")
                pid = peer_data.get("peer_id", "")
                if not endpoint or not pid or pid == self._identity.peer_id:
                    continue
                if self._registry.is_connected(pid):
                    continue
                try:
                    conn = await connect_to_peer(endpoint, self._keypair, self._identity)
                    self._registry.register(conn)
                    connected += 1
                except Exception as exc:
                    logger.debug("Failed to connect to discovered peer %s: %s", pid[:12], exc)

        return connected

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        keypair: KeyPair,
        local_identity: PeerIdentity,
        peer_registry: PeerRegistry,
    ) -> DiscoveryService:
        """Build from vex.toml config."""
        net_cfg = config.get("network", {})

        static_peers = []
        for peer_cfg in net_cfg.get("peers", []):
            static_peers.append(
                StaticPeer(
                    peer_id=peer_cfg.get("peer_id", ""),
                    display_name=peer_cfg.get("display_name", "Unknown"),
                    endpoint=peer_cfg.get("endpoint", ""),
                )
            )

        registry_cfg = net_cfg.get("registry", {})
        return cls(
            keypair=keypair,
            local_identity=local_identity,
            peer_registry=peer_registry,
            static_peers=static_peers,
            registry_url=registry_cfg.get("url", ""),
            discoverable=net_cfg.get("discoverable", True),
        )
