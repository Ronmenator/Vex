"""Ed25519 identity management for VexNet peers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


@dataclass(frozen=True)
class PeerIdentity:
    """A VexNet peer's public identity."""

    peer_id: str  # SHA-256 fingerprint of public key (64 hex chars)
    public_key_bytes: bytes  # 32-byte Ed25519 public key (raw)
    display_name: str
    capabilities: list[str]  # Advertised tool groups (e.g., ["web", "coding"])
    endpoint: str  # WebSocket URL (e.g., "ws://192.168.1.5:9120")

    def to_dict(self) -> dict:
        """Serialize for protocol messages (bytes -> hex)."""
        return {
            "peer_id": self.peer_id,
            "public_key": self.public_key_bytes.hex(),
            "display_name": self.display_name,
            "capabilities": list(self.capabilities),
            "endpoint": self.endpoint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PeerIdentity:
        """Deserialize from protocol message."""
        return cls(
            peer_id=data["peer_id"],
            public_key_bytes=bytes.fromhex(data["public_key"]),
            display_name=data["display_name"],
            capabilities=data["capabilities"],
            endpoint=data["endpoint"],
        )


class KeyPair:
    """Ed25519 keypair for signing and verification."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._public_bytes = self._public_key.public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self._peer_id = hashlib.sha256(self._public_bytes).hexdigest()

    @classmethod
    def generate(cls) -> KeyPair:
        """Generate a new Ed25519 keypair."""
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_file(cls, path: str | Path) -> KeyPair:
        """Load a keypair from a PEM file."""
        data = Path(path).read_bytes()
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        private_key = load_pem_private_key(data, password=None)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Key file does not contain an Ed25519 private key")
        return cls(private_key)

    def save(self, path: str | Path) -> None:
        """Save the private key to a PEM file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        pem = self._private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
        p.write_bytes(pem)

    @property
    def peer_id(self) -> str:
        return self._peer_id

    @property
    def public_key_bytes(self) -> bytes:
        return self._public_bytes

    @property
    def public_key_hex(self) -> str:
        return self._public_bytes.hex()

    def sign(self, data: bytes) -> bytes:
        """Sign data with the private key. Returns 64-byte signature."""
        return self._private_key.sign(data)

    def identity(
        self,
        display_name: str,
        capabilities: list[str],
        endpoint: str,
    ) -> PeerIdentity:
        """Build a PeerIdentity from this keypair + config."""
        return PeerIdentity(
            peer_id=self._peer_id,
            public_key_bytes=self._public_bytes,
            display_name=display_name,
            capabilities=capabilities,
            endpoint=endpoint,
        )


def verify_signature(public_key_bytes: bytes, data: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature. Returns False on invalid signature."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        pub.verify(signature, data)
        return True
    except Exception:
        return False


def load_or_create_keypair(key_path: str | Path) -> KeyPair:
    """Load an existing keypair or generate a new one."""
    p = Path(key_path)
    if p.is_file():
        return KeyPair.from_file(p)
    kp = KeyPair.generate()
    kp.save(p)
    return kp
