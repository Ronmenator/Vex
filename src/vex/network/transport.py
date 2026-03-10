"""WebSocket transport layer with mutual Ed25519 authentication."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Coroutine

import websockets
from websockets.asyncio.client import ClientConnection, connect
from websockets.asyncio.server import Server, ServerConnection, serve

from vex.network.identity import KeyPair, PeerIdentity, verify_signature
from vex.network.protocol import Envelope, MessageType

logger = logging.getLogger(__name__)

# Handshake timeout in seconds
_HANDSHAKE_TIMEOUT = 10.0


@dataclass
class AuthenticatedConnection:
    """A WebSocket connection that has completed mutual authentication."""

    ws: ServerConnection | ClientConnection
    remote_identity: PeerIdentity
    local_identity: PeerIdentity

    async def send(self, envelope: Envelope) -> None:
        """Send an envelope over the connection."""
        await self.ws.send(envelope.to_json())

    async def recv(self) -> Envelope:
        """Receive an envelope from the connection."""
        data = await self.ws.recv()
        if isinstance(data, bytes):
            data = data.decode()
        return Envelope.from_json(data)

    async def close(self) -> None:
        await self.ws.close()

    @property
    def remote_peer_id(self) -> str:
        return self.remote_identity.peer_id


# Handler type for inbound messages
MessageHandler = Callable[[AuthenticatedConnection, Envelope], Coroutine[Any, Any, None]]


async def _do_server_handshake(
    ws: ServerConnection,
    keypair: KeyPair,
    local_identity: PeerIdentity,
) -> AuthenticatedConnection:
    """Server-side mutual authentication handshake.

    Protocol:
    1. Server <- Client: HELLO (client's identity)
    2. Server -> Client: CHALLENGE (32 random bytes)
    3. Server <- Client: CHALLENGE_RESPONSE (client's signature of challenge)
    4. Verify client's signature
    5. Server -> Client: HELLO (server's identity)
    6. Server <- Client: CHALLENGE (32 random bytes from client)
    7. Server -> Client: CHALLENGE_RESPONSE (server's signature)
    8. Server <- Client: AUTHENTICATED
    """
    # Step 1: Receive client HELLO
    raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
    hello = Envelope.from_json(raw if isinstance(raw, str) else raw.decode())
    if hello.message_type != MessageType.HELLO:
        raise ConnectionError(f"Expected HELLO, got {hello.message_type}")

    remote_identity = PeerIdentity.from_dict(hello.payload)

    # Step 2: Send challenge
    challenge_bytes = secrets.token_bytes(32)
    challenge_env = Envelope.create(
        MessageType.CHALLENGE,
        local_identity.peer_id,
        {"challenge": challenge_bytes.hex()},
        keypair,
        recipient_id=remote_identity.peer_id,
    )
    await ws.send(challenge_env.to_json())

    # Step 3: Receive client's response
    raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
    response = Envelope.from_json(raw if isinstance(raw, str) else raw.decode())
    if response.message_type != MessageType.CHALLENGE_RESPONSE:
        raise ConnectionError(f"Expected CHALLENGE_RESPONSE, got {response.message_type}")

    # Step 4: Verify client's signature
    client_sig = bytes.fromhex(response.payload["signature"])
    if not verify_signature(remote_identity.public_key_bytes, challenge_bytes, client_sig):
        fail = Envelope.create(
            MessageType.AUTH_FAILED,
            local_identity.peer_id,
            {"reason": "Invalid signature"},
            keypair,
        )
        await ws.send(fail.to_json())
        raise ConnectionError("Client authentication failed: invalid signature")

    # Step 5: Send server HELLO
    server_hello = Envelope.create(
        MessageType.HELLO,
        local_identity.peer_id,
        local_identity.to_dict(),
        keypair,
        recipient_id=remote_identity.peer_id,
    )
    await ws.send(server_hello.to_json())

    # Step 6: Receive client's challenge
    raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
    client_challenge = Envelope.from_json(raw if isinstance(raw, str) else raw.decode())
    if client_challenge.message_type != MessageType.CHALLENGE:
        raise ConnectionError(f"Expected CHALLENGE, got {client_challenge.message_type}")

    server_challenge_bytes = bytes.fromhex(client_challenge.payload["challenge"])

    # Step 7: Sign and respond
    server_sig = keypair.sign(server_challenge_bytes)
    server_response = Envelope.create(
        MessageType.CHALLENGE_RESPONSE,
        local_identity.peer_id,
        {"signature": server_sig.hex()},
        keypair,
        recipient_id=remote_identity.peer_id,
    )
    await ws.send(server_response.to_json())

    # Step 8: Wait for AUTHENTICATED
    raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
    auth_msg = Envelope.from_json(raw if isinstance(raw, str) else raw.decode())
    if auth_msg.message_type != MessageType.AUTHENTICATED:
        raise ConnectionError(f"Expected AUTHENTICATED, got {auth_msg.message_type}")

    logger.info("Authenticated peer %s (%s)", remote_identity.display_name, remote_identity.peer_id[:12])
    return AuthenticatedConnection(ws=ws, remote_identity=remote_identity, local_identity=local_identity)


async def _do_client_handshake(
    ws: ClientConnection,
    keypair: KeyPair,
    local_identity: PeerIdentity,
) -> AuthenticatedConnection:
    """Client-side mutual authentication handshake (mirror of server)."""
    # Step 1: Send HELLO
    hello = Envelope.create(
        MessageType.HELLO,
        local_identity.peer_id,
        local_identity.to_dict(),
        keypair,
    )
    await ws.send(hello.to_json())

    # Step 2: Receive server challenge
    raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
    challenge = Envelope.from_json(raw if isinstance(raw, str) else raw.decode())
    if challenge.message_type != MessageType.CHALLENGE:
        raise ConnectionError(f"Expected CHALLENGE, got {challenge.message_type}")

    challenge_bytes = bytes.fromhex(challenge.payload["challenge"])

    # Step 3: Sign and respond
    sig = keypair.sign(challenge_bytes)
    response = Envelope.create(
        MessageType.CHALLENGE_RESPONSE,
        local_identity.peer_id,
        {"signature": sig.hex()},
        keypair,
    )
    await ws.send(response.to_json())

    # Step 5: Receive server HELLO
    raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
    server_hello = Envelope.from_json(raw if isinstance(raw, str) else raw.decode())
    if server_hello.message_type == MessageType.AUTH_FAILED:
        raise ConnectionError(f"Server rejected auth: {server_hello.payload.get('reason', 'unknown')}")
    if server_hello.message_type != MessageType.HELLO:
        raise ConnectionError(f"Expected HELLO, got {server_hello.message_type}")

    remote_identity = PeerIdentity.from_dict(server_hello.payload)

    # Step 6: Send our challenge
    our_challenge = secrets.token_bytes(32)
    challenge_env = Envelope.create(
        MessageType.CHALLENGE,
        local_identity.peer_id,
        {"challenge": our_challenge.hex()},
        keypair,
        recipient_id=remote_identity.peer_id,
    )
    await ws.send(challenge_env.to_json())

    # Step 7: Receive server's response
    raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT)
    server_response = Envelope.from_json(raw if isinstance(raw, str) else raw.decode())
    if server_response.message_type != MessageType.CHALLENGE_RESPONSE:
        raise ConnectionError(f"Expected CHALLENGE_RESPONSE, got {server_response.message_type}")

    server_sig = bytes.fromhex(server_response.payload["signature"])
    if not verify_signature(remote_identity.public_key_bytes, our_challenge, server_sig):
        raise ConnectionError("Server authentication failed: invalid signature")

    # Step 8: Send AUTHENTICATED
    auth = Envelope.create(
        MessageType.AUTHENTICATED,
        local_identity.peer_id,
        {},
        keypair,
        recipient_id=remote_identity.peer_id,
    )
    await ws.send(auth.to_json())

    logger.info("Connected to peer %s (%s)", remote_identity.display_name, remote_identity.peer_id[:12])
    return AuthenticatedConnection(ws=ws, remote_identity=remote_identity, local_identity=local_identity)


class TransportServer:
    """WebSocket server that authenticates inbound peer connections."""

    def __init__(
        self,
        keypair: KeyPair,
        local_identity: PeerIdentity,
        on_connect: Callable[[AuthenticatedConnection], Coroutine[Any, Any, None]],
        on_message: MessageHandler,
        on_disconnect: Callable[[str], Coroutine[Any, Any, None]],
        host: str = "0.0.0.0",
        port: int = 9120,
    ) -> None:
        self._keypair = keypair
        self._identity = local_identity
        self._on_connect = on_connect
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._host = host
        self._port = port
        self._server: Server | None = None

    async def start(self) -> None:
        self._server = await serve(self._handle_connection, self._host, self._port)
        logger.info("VexNet listening on ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("VexNet server stopped")

    async def _handle_connection(self, ws: ServerConnection) -> None:
        peer_id = ""
        try:
            conn = await _do_server_handshake(ws, self._keypair, self._identity)
            peer_id = conn.remote_peer_id
            await self._on_connect(conn)

            async for raw in ws:
                data = raw if isinstance(raw, str) else raw.decode()
                envelope = Envelope.from_json(data)
                await self._on_message(conn, envelope)

        except Exception as exc:
            logger.warning("Connection error: %s", exc)
        finally:
            if peer_id:
                await self._on_disconnect(peer_id)


async def connect_to_peer(
    endpoint: str,
    keypair: KeyPair,
    local_identity: PeerIdentity,
) -> AuthenticatedConnection:
    """Connect to a remote peer and perform mutual authentication."""
    ws = await connect(endpoint)
    return await _do_client_handshake(ws, keypair, local_identity)
