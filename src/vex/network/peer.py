"""Peer connection state and registry."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vex.network.identity import PeerIdentity
from vex.network.protocol import Envelope
from vex.network.transport import AuthenticatedConnection

logger = logging.getLogger(__name__)


@dataclass
class PeerState:
    """Runtime state for a connected peer."""

    identity: PeerIdentity
    connection: AuthenticatedConnection
    connected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active_tasks: int = 0

    def touch(self) -> None:
        self.last_seen = datetime.now(timezone.utc).isoformat()


class PeerRegistry:
    """Tracks all connected peers and known (cached) peers."""

    def __init__(self, data_dir: str) -> None:
        self._connected: dict[str, PeerState] = {}
        self._known: dict[str, dict[str, Any]] = {}  # peer_id -> serialized identity
        self._data_dir = Path(data_dir)
        self._peers_file = self._data_dir / "peers.jsonl"
        self._load_known()

    def _load_known(self) -> None:
        """Load cached known peers from JSONL."""
        if self._peers_file.is_file():
            for line in self._peers_file.read_text().strip().splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self._known[entry["peer_id"]] = entry

    def _save_known(self) -> None:
        """Persist known peers to JSONL."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(v, separators=(",", ":")) for v in self._known.values()]
        self._peers_file.write_text("\n".join(lines) + "\n" if lines else "")

    def register(self, conn: AuthenticatedConnection) -> PeerState:
        """Register a newly authenticated connection."""
        identity = conn.remote_identity
        state = PeerState(identity=identity, connection=conn)
        self._connected[identity.peer_id] = state

        # Cache the identity for future discovery
        self._known[identity.peer_id] = identity.to_dict()
        self._save_known()

        logger.info("Peer registered: %s (%s)", identity.display_name, identity.peer_id[:12])
        return state

    def unregister(self, peer_id: str) -> PeerState | None:
        """Remove a disconnected peer. Returns the removed state or None."""
        state = self._connected.pop(peer_id, None)
        if state:
            logger.info("Peer disconnected: %s", state.identity.display_name)
        return state

    def get(self, peer_id: str) -> PeerState | None:
        """Get a connected peer by ID."""
        return self._connected.get(peer_id)

    def get_connected(self) -> list[PeerState]:
        """All currently connected peers."""
        return list(self._connected.values())

    def get_known(self) -> list[dict[str, Any]]:
        """All known peers (connected or cached from past sessions)."""
        return list(self._known.values())

    def is_connected(self, peer_id: str) -> bool:
        return peer_id in self._connected

    def connected_count(self) -> int:
        return len(self._connected)

    def find_by_capability(self, capability: str) -> list[PeerState]:
        """Find connected peers advertising a specific capability."""
        return [
            state
            for state in self._connected.values()
            if capability in state.identity.capabilities
        ]

    async def broadcast(self, envelope: Envelope, *, exclude: str | None = None) -> int:
        """Send an envelope to all connected peers. Returns count sent."""
        sent = 0
        for peer_id, state in list(self._connected.items()):
            if peer_id == exclude:
                continue
            try:
                await state.connection.send(envelope)
                sent += 1
            except Exception as exc:
                logger.warning("Failed to send to %s: %s", peer_id[:12], exc)
        return sent

    async def send_to(self, peer_id: str, envelope: Envelope) -> bool:
        """Send an envelope to a specific peer. Returns True on success."""
        state = self._connected.get(peer_id)
        if not state:
            return False
        try:
            await state.connection.send(envelope)
            return True
        except Exception as exc:
            logger.warning("Failed to send to %s: %s", peer_id[:12], exc)
            return False
