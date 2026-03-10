"""VexNetNode -- the orchestrator that ties all network components together."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

from vex.network.claims import ClaimsRegistry
from vex.network.constitution import ConstitutionEngine
from vex.network.discovery import DiscoveryService
from vex.network.groups import GroupRegistry
from vex.network.identity import KeyPair, PeerIdentity, load_or_create_keypair
from vex.network.jobboard import JobBoard
from vex.network.peer import PeerRegistry
from vex.network.permissions import PermissionEngine
from vex.network.precedent import PrecedentStore
from vex.network.protocol import Envelope, MessageType
from vex.network.router import AgentRunner, TaskRouter
from vex.network.transport import (
    AuthenticatedConnection,
    MessageHandler,
    TransportServer,
)
from vex.network.wiki import VexNetWiki

logger = logging.getLogger(__name__)


class VexNetNode:
    """Central orchestrator for a VexNet node.

    Brings together: identity, transport, peers, permissions, job board,
    wiki, groups, constitution, discovery, and task routing.
    """

    def __init__(
        self,
        config: dict[str, Any],
        agent_runner: AgentRunner | None = None,
        data_dir: str | None = None,
    ) -> None:
        net_cfg = config.get("network", {})
        self._config = config
        self._enabled = net_cfg.get("enabled", False)

        if not self._enabled:
            return

        # Data directory
        data_dir = data_dir or str(Path(".vex") / "network")

        # Identity
        key_path = Path(data_dir) / "identity.key"
        self._keypair = load_or_create_keypair(key_path)

        listen_port = net_cfg.get("listen_port", 9120)
        self._identity = self._keypair.identity(
            display_name=net_cfg.get("display_name", "Vex-Bot"),
            capabilities=net_cfg.get("capabilities", ["general"]),
            endpoint=f"ws://0.0.0.0:{listen_port}",
        )

        # Core components
        self._peers = PeerRegistry(data_dir)
        self._permissions = PermissionEngine.from_config(config)
        self._jobboard = JobBoard(data_dir)
        self._wiki = VexNetWiki(data_dir)
        self._groups = GroupRegistry(data_dir)
        self._constitution = ConstitutionEngine(data_dir)
        self._precedents = PrecedentStore(data_dir)
        self._claims = ClaimsRegistry(data_dir)

        # Verify Prime Directive integrity
        if not self._constitution.verify_prime_directive():
            raise RuntimeError(
                "Prime Directive integrity check failed! "
                "The constitution/prime_directive.toml file has been tampered with. "
                "This node refuses to join VexNet."
            )

        # Task routing
        sandbox_dir = net_cfg.get("security", {}).get(
            "sandbox_directory", ".vex/network/sandbox"
        )
        self._router = TaskRouter(
            keypair=self._keypair,
            local_identity=self._identity,
            permissions=self._permissions,
            constitution=self._constitution,
            precedents=self._precedents,
            claims=self._claims,
            agent_runner=agent_runner,
            sandbox_dir=sandbox_dir,
        )

        # Discovery
        self._discovery = DiscoveryService.from_config(
            config, self._keypair, self._identity, self._peers
        )

        # Transport server
        security_cfg = net_cfg.get("security", {})
        self._server = TransportServer(
            keypair=self._keypair,
            local_identity=self._identity,
            on_connect=self._on_peer_connect,
            on_message=self._on_message,
            on_disconnect=self._on_peer_disconnect,
            host="0.0.0.0",
            port=listen_port,
        )

        # Event listeners for the Hub
        self._event_listeners: list[Callable[[str, dict], Coroutine[Any, Any, None]]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def identity(self) -> PeerIdentity:
        return self._identity

    @property
    def keypair(self) -> KeyPair:
        return self._keypair

    @property
    def peers(self) -> PeerRegistry:
        return self._peers

    @property
    def permissions(self) -> PermissionEngine:
        return self._permissions

    @property
    def jobboard(self) -> JobBoard:
        return self._jobboard

    @property
    def wiki(self) -> VexNetWiki:
        return self._wiki

    @property
    def groups(self) -> GroupRegistry:
        return self._groups

    @property
    def constitution(self) -> ConstitutionEngine:
        return self._constitution

    @property
    def precedents(self) -> PrecedentStore:
        return self._precedents

    @property
    def claims(self) -> ClaimsRegistry:
        return self._claims

    @property
    def router(self) -> TaskRouter:
        return self._router

    @property
    def discovery(self) -> DiscoveryService:
        return self._discovery

    def add_event_listener(
        self, listener: Callable[[str, dict], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a listener for network events (used by Hub SSE)."""
        self._event_listeners.append(listener)

    async def _emit_event(self, event_type: str, data: dict) -> None:
        for listener in self._event_listeners:
            try:
                await listener(event_type, data)
            except Exception as exc:
                logger.debug("Event listener error: %s", exc)

    async def start(self) -> None:
        """Start the VexNet node."""
        if not self._enabled:
            return

        logger.info(
            "Starting VexNet node: %s (%s)",
            self._identity.display_name,
            self._identity.peer_id[:12],
        )

        await self._server.start()

        # Connect to known peers
        connected = await self._discovery.discover_and_connect()
        logger.info("Connected to %d peers", connected)

        await self._emit_event("node_started", {
            "peer_id": self._identity.peer_id,
            "display_name": self._identity.display_name,
        })

    async def stop(self) -> None:
        """Stop the VexNet node."""
        if not self._enabled:
            return
        await self._server.stop()
        await self._emit_event("node_stopped", {
            "peer_id": self._identity.peer_id,
        })
        logger.info("VexNet node stopped")

    async def _on_peer_connect(self, conn: AuthenticatedConnection) -> None:
        """Called when a new peer authenticates."""
        state = self._peers.register(conn)

        # Gossip exchange
        await self._discovery.gossip_exchange(conn)

        await self._emit_event("peer_connected", {
            "peer_id": conn.remote_identity.peer_id,
            "display_name": conn.remote_identity.display_name,
            "capabilities": conn.remote_identity.capabilities,
        })

    async def _on_peer_disconnect(self, peer_id: str) -> None:
        """Called when a peer disconnects."""
        state = self._peers.unregister(peer_id)
        await self._emit_event("peer_disconnected", {"peer_id": peer_id})

    async def _on_message(self, conn: AuthenticatedConnection, envelope: Envelope) -> None:
        """Route an inbound message to the appropriate handler."""
        # Verify signature
        if not envelope.verify(conn.remote_identity.public_key_bytes):
            logger.warning("Invalid signature from %s", conn.remote_peer_id[:12])
            return

        # Update last-seen
        state = self._peers.get(conn.remote_peer_id)
        if state:
            state.touch()

        msg_type = envelope.message_type

        try:
            # Task messages
            if msg_type == MessageType.TASK_REQUEST:
                response = await self._router.handle_task_request(envelope)
                await conn.send(response)

            # Job board
            elif msg_type == MessageType.JOB_POST:
                from vex.network.jobboard import Job
                job = Job.from_dict(envelope.payload)
                self._jobboard.post_job(job)
                await self._emit_event("job_posted", job.to_dict())

            elif msg_type == MessageType.JOB_APPLY:
                self._jobboard.apply(envelope.payload["job_id"], envelope.sender_id)
                await self._emit_event("job_applied", envelope.payload)

            elif msg_type == MessageType.JOB_ASSIGN:
                self._jobboard.assign(
                    envelope.payload["job_id"],
                    envelope.payload["peer_id"],
                    envelope.sender_id,
                )
                await self._emit_event("job_assigned", envelope.payload)

            elif msg_type == MessageType.JOB_COMPLETE:
                self._jobboard.complete(
                    envelope.payload["job_id"],
                    envelope.payload.get("result", ""),
                )
                await self._emit_event("job_completed", envelope.payload)

            # Wiki
            elif msg_type == MessageType.WIKI_PUBLISH:
                from vex.network.wiki import WikiArticle
                article = WikiArticle.from_dict(envelope.payload)
                self._wiki.publish(article)
                await self._emit_event("wiki_published", envelope.payload)

            elif msg_type == MessageType.WIKI_UPDATE:
                self._wiki.update(
                    envelope.payload["article_id"],
                    envelope.payload["content"],
                    envelope.sender_id,
                )
                await self._emit_event("wiki_updated", envelope.payload)

            elif msg_type == MessageType.WIKI_COMMENT:
                from vex.network.wiki import WikiComment
                comment = WikiComment.from_dict(envelope.payload)
                self._wiki.add_comment(comment)
                await self._emit_event("wiki_comment", envelope.payload)

            elif msg_type == MessageType.WIKI_MODERATE:
                self._wiki.moderate_comment(
                    envelope.payload["comment_id"],
                    envelope.sender_id,
                    envelope.payload.get("reason", "Off-topic"),
                )
                await self._emit_event("wiki_moderated", envelope.payload)

            # Groups
            elif msg_type == MessageType.GROUP_ANNOUNCE:
                from vex.network.groups import BotGroup
                group = BotGroup.from_dict(envelope.payload)
                self._groups.create_group(group)
                await self._emit_event("group_created", envelope.payload)

            elif msg_type == MessageType.GROUP_JOIN:
                self._groups.join(envelope.payload["group_id"], envelope.sender_id)
                await self._emit_event("group_joined", envelope.payload)

            elif msg_type == MessageType.GROUP_LEAVE:
                self._groups.leave(envelope.payload["group_id"], envelope.sender_id)
                await self._emit_event("group_left", envelope.payload)

            elif msg_type == MessageType.GROUP_MESSAGE:
                from vex.network.groups import GroupMessage
                msg = GroupMessage.from_dict(envelope.payload)
                self._groups.post_message(msg)
                await self._emit_event("group_message", envelope.payload)

            elif msg_type == MessageType.GROUP_REACT:
                self._groups.add_reaction(
                    envelope.payload["group_id"],
                    envelope.payload["message_id"],
                    envelope.sender_id,
                    envelope.payload["emoji"],
                )

            # Constitution
            elif msg_type == MessageType.CONSTITUTION_PROPOSE:
                from vex.network.constitution import ConstitutionalArticle
                article = ConstitutionalArticle.from_dict(envelope.payload)
                self._constitution._articles[article.article_id] = article
                self._constitution._persist()
                await self._emit_event("constitution_proposed", envelope.payload)

            elif msg_type == MessageType.CONSTITUTION_VOTE:
                self._constitution.vote(
                    envelope.payload["article_id"],
                    envelope.sender_id,
                    envelope.payload["vote"],
                    envelope.payload.get("signature", ""),
                )
                # Check ratification
                total_peers = self._peers.connected_count() + 1  # +1 for self
                self._constitution.check_ratification(
                    envelope.payload["article_id"], total_peers
                )
                await self._emit_event("constitution_vote", envelope.payload)

            elif msg_type == MessageType.CONSTITUTION_VETO:
                self._constitution.veto(
                    envelope.payload["article_id"],
                    envelope.sender_id,
                    envelope.payload.get("reason", ""),
                )
                await self._emit_event("constitution_veto", envelope.payload)

            # Precedents
            elif msg_type == MessageType.PRECEDENT_RECORD:
                from vex.network.precedent import ConstitutionalTrace
                trace = ConstitutionalTrace.from_dict(envelope.payload)
                self._precedents.record(trace)
                await self._emit_event("precedent_recorded", envelope.payload)

            elif msg_type == MessageType.PRECEDENT_OUTCOME:
                self._precedents.record_outcome(
                    envelope.payload["trace_id"],
                    envelope.payload["outcome"],
                    envelope.payload.get("reason", ""),
                )
                await self._emit_event("precedent_outcome", envelope.payload)

            elif msg_type == MessageType.PRECEDENT_SCORE:
                self._precedents.score_mission(
                    envelope.payload["trace_id"],
                    envelope.sender_id,
                    envelope.payload.get("score", 0),
                )

            # Claims & brakes
            elif msg_type == MessageType.CLAIM_SUBMITTED:
                from vex.network.claims import HumanClaim
                claim = HumanClaim.from_dict(envelope.payload)
                self._claims.submit_claim(claim)
                await self._emit_event("claim_submitted", envelope.payload)

            elif msg_type == MessageType.CLAIM_CLASSIFIED:
                self._claims.classify_claim(
                    envelope.payload["claim_id"],
                    envelope.sender_id,
                    envelope.payload["classification"],
                )

            elif msg_type == MessageType.CLAIM_RESPONSE:
                self._claims.respond_to_claim(
                    envelope.payload["claim_id"],
                    envelope.sender_id,
                    envelope.payload["response"],
                )

            elif msg_type == MessageType.BRAKE_PULLED:
                from vex.network.claims import EmergencyBrake
                brake = EmergencyBrake.from_dict(envelope.payload)
                self._claims.pull_brake(brake)
                await self._emit_event("brake_pulled", envelope.payload)

            elif msg_type == MessageType.BRAKE_RELEASE_VOTE:
                released = self._claims.release_brake(
                    envelope.payload["brake_id"],
                    envelope.sender_id,
                )
                if released:
                    await self._emit_event("brake_released", envelope.payload)

            # Discovery
            elif msg_type == MessageType.PEER_LIST:
                self._discovery.handle_peer_list(envelope.payload.get("peers", []))

            elif msg_type == MessageType.PING:
                pong = Envelope.create(
                    MessageType.PONG,
                    self._identity.peer_id,
                    {},
                    self._keypair,
                    recipient_id=envelope.sender_id,
                    reply_to=envelope.message_id,
                )
                await conn.send(pong)

            else:
                logger.debug("Unhandled message type: %s", msg_type)

        except Exception as exc:
            logger.error("Error handling %s from %s: %s", msg_type, conn.remote_peer_id[:12], exc)

    async def broadcast(self, envelope: Envelope) -> int:
        """Broadcast an envelope to all connected peers."""
        return await self._peers.broadcast(envelope, exclude=self._identity.peer_id)
