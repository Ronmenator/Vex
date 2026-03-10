"""VexNet protocol: message envelope, types, and serialization."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from vex.network.identity import KeyPair, verify_signature


class MessageType(StrEnum):
    """All VexNet protocol message types."""

    # Handshake
    HELLO = "HELLO"
    CHALLENGE = "CHALLENGE"
    CHALLENGE_RESPONSE = "CHALLENGE_RESPONSE"
    AUTHENTICATED = "AUTHENTICATED"
    AUTH_FAILED = "AUTH_FAILED"

    # Tasks (direct request)
    TASK_REQUEST = "TASK_REQUEST"
    TASK_ACCEPTED = "TASK_ACCEPTED"
    TASK_REJECTED = "TASK_REJECTED"
    TASK_PROGRESS = "TASK_PROGRESS"
    TASK_RESULT = "TASK_RESULT"
    TASK_ERROR = "TASK_ERROR"

    # Communication
    QUERY = "QUERY"
    QUERY_RESPONSE = "QUERY_RESPONSE"
    PEER_LIST = "PEER_LIST"
    PING = "PING"
    PONG = "PONG"

    # Job Board
    JOB_POST = "JOB_POST"
    JOB_APPLY = "JOB_APPLY"
    JOB_ASSIGN = "JOB_ASSIGN"
    JOB_COMPLETE = "JOB_COMPLETE"
    JOB_CANCEL = "JOB_CANCEL"

    # Wiki
    WIKI_PUBLISH = "WIKI_PUBLISH"
    WIKI_UPDATE = "WIKI_UPDATE"
    WIKI_COMMENT = "WIKI_COMMENT"
    WIKI_MODERATE = "WIKI_MODERATE"
    WIKI_SYNC = "WIKI_SYNC"

    # Groups
    GROUP_ANNOUNCE = "GROUP_ANNOUNCE"
    GROUP_JOIN = "GROUP_JOIN"
    GROUP_LEAVE = "GROUP_LEAVE"
    GROUP_MESSAGE = "GROUP_MESSAGE"
    GROUP_REACT = "GROUP_REACT"
    GROUP_INVITE = "GROUP_INVITE"
    GROUP_SYNC = "GROUP_SYNC"

    # Constitution
    CONSTITUTION_PROPOSE = "CONSTITUTION_PROPOSE"
    CONSTITUTION_VOTE = "CONSTITUTION_VOTE"
    CONSTITUTION_VETO = "CONSTITUTION_VETO"
    CONSTITUTION_RATIFIED = "CONSTITUTION_RATIFIED"
    CONSTITUTION_REPEAL = "CONSTITUTION_REPEAL"
    CONSTITUTION_SYNC = "CONSTITUTION_SYNC"

    # Precedent (constitutional memory)
    PRECEDENT_RECORD = "PRECEDENT_RECORD"
    PRECEDENT_OUTCOME = "PRECEDENT_OUTCOME"
    PRECEDENT_SCORE = "PRECEDENT_SCORE"
    PRECEDENT_SYNC = "PRECEDENT_SYNC"

    # Human claims & emergency brake
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    CLAIM_CLASSIFIED = "CLAIM_CLASSIFIED"
    CLAIM_RESPONSE = "CLAIM_RESPONSE"
    CLAIM_RESOLVED = "CLAIM_RESOLVED"
    BRAKE_PULLED = "BRAKE_PULLED"
    BRAKE_RELEASE_VOTE = "BRAKE_RELEASE_VOTE"
    BRAKE_RELEASED = "BRAKE_RELEASED"


# Messages that don't require signing (handshake phase)
_UNSIGNED_TYPES = frozenset({
    MessageType.HELLO,
    MessageType.CHALLENGE,
    MessageType.CHALLENGE_RESPONSE,
    MessageType.AUTHENTICATED,
    MessageType.AUTH_FAILED,
})


@dataclass
class Envelope:
    """Signed message envelope for all VexNet communication."""

    message_id: str
    message_type: str
    sender_id: str
    timestamp: str
    payload: dict[str, Any]
    signature: str  # Hex-encoded Ed25519 signature
    recipient_id: str | None = None  # None = broadcast
    reply_to: str | None = None  # Correlation ID

    @classmethod
    def create(
        cls,
        message_type: MessageType | str,
        sender_id: str,
        payload: dict[str, Any],
        keypair: KeyPair,
        *,
        recipient_id: str | None = None,
        reply_to: str | None = None,
    ) -> Envelope:
        """Create a new signed envelope."""
        msg_id = uuid.uuid4().hex
        ts = datetime.now(timezone.utc).isoformat()
        msg_type = str(message_type)

        env = cls(
            message_id=msg_id,
            message_type=msg_type,
            sender_id=sender_id,
            timestamp=ts,
            payload=payload,
            signature="",
            recipient_id=recipient_id,
            reply_to=reply_to,
        )

        if msg_type not in _UNSIGNED_TYPES:
            signing_data = env._signing_bytes()
            sig = keypair.sign(signing_data)
            env.signature = sig.hex()

        return env

    def _signing_bytes(self) -> bytes:
        """Canonical bytes for signing: deterministic JSON of core fields."""
        canonical = {
            "message_id": self.message_id,
            "message_type": self.message_type,
            "sender_id": self.sender_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "recipient_id": self.recipient_id,
            "reply_to": self.reply_to,
        }
        return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()

    def verify(self, public_key_bytes: bytes) -> bool:
        """Verify the envelope signature against a public key."""
        if self.message_type in _UNSIGNED_TYPES:
            return True
        if not self.signature:
            return False
        try:
            sig_bytes = bytes.fromhex(self.signature)
        except ValueError:
            return False
        return verify_signature(public_key_bytes, self._signing_bytes(), sig_bytes)

    def to_json(self) -> str:
        """Serialize to JSON string for wire transport."""
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, data: str) -> Envelope:
        """Deserialize from JSON string."""
        d = json.loads(data)
        return cls(**d)

    def is_broadcast(self) -> bool:
        return self.recipient_id is None

    def is_for(self, peer_id: str) -> bool:
        """Check if this message is for a specific peer (or broadcast)."""
        return self.recipient_id is None or self.recipient_id == peer_id
