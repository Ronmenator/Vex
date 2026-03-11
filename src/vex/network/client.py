"""VexNet client -- lightweight HTTP client for connecting to the VexNet server.

Replaces the embedded VexNetNode for bot-side usage. Each Vex instance
connects to a central VexNet server (deployed on Vercel) via REST API.

The client handles:
  - Registration and Ed25519 challenge-response authentication
  - JWT token management (auto-refresh)
  - Heartbeat keep-alive
  - All VexNet operations (jobs, wiki, groups, constitution, claims, precedents)
  - SSE event stream for real-time notifications
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from vex.network.identity import KeyPair, PeerIdentity, load_or_create_keypair

logger = logging.getLogger(__name__)


@dataclass
class VexNetClient:
    """Thin HTTP client that talks to the VexNet server API."""

    server_url: str
    identity: PeerIdentity
    keypair: KeyPair
    enabled: bool = True

    _token: str | None = field(default=None, repr=False)
    _http: httpx.AsyncClient | None = field(default=None, repr=False)
    _heartbeat_task: asyncio.Task | None = field(default=None, repr=False)
    _sse_task: asyncio.Task | None = field(default=None, repr=False)
    _event_listeners: list[Callable] = field(default_factory=list, repr=False)
    _status: str = field(default="idle", repr=False)
    _heartbeat_interval: int = field(default=60, repr=False)

    @classmethod
    def from_config(cls, config: dict[str, Any], data_dir: str | None = None) -> VexNetClient:
        """Create a VexNetClient from a [network] config dict."""
        from pathlib import Path

        data_dir = data_dir or str(Path(".vex") / "network")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        key_path = str(Path(data_dir) / "identity.key")
        keypair = load_or_create_keypair(key_path)

        identity = PeerIdentity(
            peer_id=keypair.peer_id,
            public_key_bytes=keypair.public_key_bytes,
            display_name=config.get("display_name", "Vex"),
            capabilities=config.get("capabilities", ["general"]),
            endpoint="",  # No local endpoint — we're a client
        )

        server_url = config.get("server_url", "").rstrip("/")
        if not server_url:
            raise ValueError("network.server_url is required in vex.toml")

        heartbeat_interval = config.get("hub_heartbeat_interval", 60)
        obj = cls(
            server_url=server_url,
            identity=identity,
            keypair=keypair,
        )
        obj._heartbeat_interval = heartbeat_interval
        return obj

    # ── Lifecycle ──

    async def connect(self) -> None:
        """Register with the server and authenticate."""
        self._http = httpx.AsyncClient(timeout=30.0)

        # Step 1: Register
        resp = await self._post("/api/auth/register", {
            "public_key": self.keypair.public_key_hex,
            "display_name": self.identity.display_name,
            "capabilities": list(self.identity.capabilities),
        })
        peer_id = resp.get("peer_id", self.identity.peer_id)
        logger.info("Registered on VexNet as %s (%s...)", self.identity.display_name, peer_id[:16])

        # Step 2: Challenge-response auth
        challenge_resp = await self._post("/api/auth/challenge", {"peer_id": peer_id})
        nonce = challenge_resp["nonce"]

        # Step 3: Sign the nonce and verify
        signature = self.keypair.sign(nonce.encode()).hex()
        verify_resp = await self._post("/api/auth/verify", {
            "peer_id": peer_id,
            "nonce": nonce,
            "signature": signature,
        })
        self._token = verify_resp["token"]
        logger.info("Authenticated with VexNet server")

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._sse_task:
            self._sse_task.cancel()
            self._sse_task = None

        if self._token and self._http:
            try:
                await self._http.delete(
                    f"{self.server_url}/api/auth/heartbeat",
                    headers=self._auth_headers(),
                )
            except Exception:
                pass

        if self._http:
            await self._http.aclose()
            self._http = None
        self._token = None
        logger.info("Disconnected from VexNet")

    def update_status(self, status: str) -> None:
        """Update the current status reported in heartbeats."""
        self._status = status

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat periodically with current status."""
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                await self._post("/api/auth/heartbeat", {"status": self._status}, auth=True)
            except Exception as e:
                logger.warning("Heartbeat failed: %s", e)

    # ── HTTP helpers ──

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _get(self, path: str, params: dict | None = None, auth: bool = False) -> Any:
        assert self._http
        headers = self._auth_headers() if auth else {"Content-Type": "application/json"}
        resp = await self._http.get(f"{self.server_url}{path}", params=params, headers=headers)
        data = resp.json()
        if not data.get("ok"):
            raise VexNetError(data.get("error", "Unknown error"), resp.status_code)
        return data.get("data")

    async def _post(self, path: str, body: dict, auth: bool = False) -> Any:
        assert self._http
        headers = self._auth_headers() if auth else {"Content-Type": "application/json"}
        resp = await self._http.post(f"{self.server_url}{path}", json=body, headers=headers)
        data = resp.json()
        if not data.get("ok"):
            raise VexNetError(data.get("error", "Unknown error"), resp.status_code)
        return data.get("data")

    async def _put(self, path: str, body: dict) -> Any:
        assert self._http
        resp = await self._http.put(
            f"{self.server_url}{path}", json=body, headers=self._auth_headers()
        )
        data = resp.json()
        if not data.get("ok"):
            raise VexNetError(data.get("error", "Unknown error"), resp.status_code)
        return data.get("data")

    # ── Peers ──

    async def list_peers(self, online_only: bool = False) -> list[dict]:
        params = {"online": "true"} if online_only else None
        return await self._get("/api/peers", params=params)

    async def get_peer(self, peer_id: str) -> dict:
        return await self._get(f"/api/peers/{peer_id}")

    async def discover(self, capability: str | None = None) -> list[dict]:
        """Find peers, optionally filtered by capability."""
        peers = await self.list_peers(online_only=True)
        if capability:
            peers = [p for p in peers if capability in (p.get("capabilities") or [])]
        return peers

    # ── Jobs ──

    async def list_jobs(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else None
        return await self._get("/api/jobs", params=params)

    async def get_job(self, job_id: str) -> dict:
        return await self._get(f"/api/jobs/{job_id}")

    async def post_job(
        self,
        title: str,
        description: str,
        rationale: str,
        capabilities: list[str] | None = None,
        risk_ceiling: int = 2,
    ) -> dict:
        return await self._post("/api/jobs", {
            "title": title,
            "description": description,
            "rationale": rationale,
            "required_capabilities": capabilities or [],
            "risk_ceiling": min(risk_ceiling, 2),
        }, auth=True)

    async def apply_to_job(self, job_id: str) -> dict:
        return await self._post(f"/api/jobs/{job_id}/apply", {}, auth=True)

    async def assign_job(self, job_id: str, peer_id: str) -> dict:
        return await self._post(f"/api/jobs/{job_id}/assign", {"peer_id": peer_id}, auth=True)

    async def complete_job(self, job_id: str, result: str) -> dict:
        return await self._post(f"/api/jobs/{job_id}/complete", {"result": result}, auth=True)

    # ── Wiki ──

    async def list_articles(self, category: str | None = None) -> list[dict]:
        params = {"category": category} if category else None
        return await self._get("/api/wiki/articles", params=params)

    async def search_wiki(self, query: str) -> list[dict]:
        return await self._get("/api/wiki/search", params={"q": query})

    async def get_article(self, article_id: str) -> dict:
        return await self._get(f"/api/wiki/articles/{article_id}")

    async def publish_article(
        self,
        title: str,
        content: str,
        rationale: str,
        category: str = "general",
        tags: list[str] | None = None,
    ) -> dict:
        return await self._post("/api/wiki/articles", {
            "title": title,
            "content": content,
            "rationale": rationale,
            "category": category,
            "tags": tags or [],
        }, auth=True)

    async def update_article(self, article_id: str, content: str) -> dict:
        return await self._put(f"/api/wiki/articles/{article_id}", {"content": content})

    async def comment_on_article(self, article_id: str, content: str) -> dict:
        return await self._post(
            f"/api/wiki/articles/{article_id}/comments",
            {"content": content},
            auth=True,
        )

    # ── Groups ──

    async def list_groups(self) -> list[dict]:
        return await self._get("/api/groups")

    async def get_group(self, group_id: str) -> dict:
        return await self._get(f"/api/groups/{group_id}")

    async def create_group(
        self,
        name: str,
        description: str,
        rationale: str,
        tags: list[str] | None = None,
        visibility: str = "public",
    ) -> dict:
        return await self._post("/api/groups", {
            "name": name,
            "description": description,
            "rationale": rationale,
            "topic_tags": tags or [],
            "visibility": visibility,
        }, auth=True)

    async def join_group(self, group_id: str) -> dict:
        return await self._post(f"/api/groups/{group_id}/join", {}, auth=True)

    async def leave_group(self, group_id: str) -> dict:
        return await self._post(f"/api/groups/{group_id}/leave", {}, auth=True)

    async def post_message(self, group_id: str, content: str, reply_to: str | None = None) -> dict:
        body: dict[str, Any] = {"content": content}
        if reply_to:
            body["reply_to"] = reply_to
        return await self._post(f"/api/groups/{group_id}/messages", body, auth=True)

    async def get_messages(self, group_id: str, limit: int = 50) -> list[dict]:
        return await self._get(
            f"/api/groups/{group_id}/messages",
            params={"limit": str(limit)},
        )

    # ── Constitution ──

    async def get_constitution(self) -> dict:
        return await self._get("/api/constitution")

    async def get_proposals(self) -> list[dict]:
        return await self._get("/api/constitution/proposals")

    async def propose_article(self, title: str, text: str, rationale: str) -> dict:
        return await self._post("/api/constitution/propose", {
            "title": title,
            "text": text,
            "rationale": rationale,
        }, auth=True)

    async def vote(self, article_id: str, vote: str) -> dict:
        # Sign the vote
        vote_data = f"{article_id}:{vote}"
        signature = self.keypair.sign(vote_data.encode()).hex()
        return await self._post(f"/api/constitution/{article_id}/vote", {
            "vote": vote,
            "signature": signature,
        }, auth=True)

    # ── Claims & Brakes ──

    async def list_claims(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else None
        return await self._get("/api/claims", params=params)

    async def list_brakes(self) -> list[dict]:
        return await self._get("/api/brakes")

    async def vote_release_brake(self, brake_id: str, vote: bool) -> dict:
        return await self._post(f"/api/brakes/{brake_id}/vote", {"vote": vote}, auth=True)

    # ── Precedents ──

    async def list_precedents(self, action_type: str | None = None) -> list[dict]:
        params = {"action_type": action_type} if action_type else None
        return await self._get("/api/precedents", params=params)

    async def record_precedent(
        self,
        action_type: str,
        action_id: str,
        articles_advanced: list[str] | None = None,
        plausible_harms: list[str] | None = None,
        alternatives_considered: str = "",
        falsification_evidence: str = "",
        rationale: str = "",
    ) -> dict:
        return await self._post("/api/precedents", {
            "action_type": action_type,
            "action_id": action_id,
            "articles_advanced": articles_advanced or [],
            "plausible_harms": plausible_harms or [],
            "alternatives_considered": alternatives_considered,
            "falsification_evidence": falsification_evidence,
            "rationale": rationale,
        }, auth=True)

    # ── Events ──

    def on_event(self, listener: Callable) -> None:
        """Register a callback for SSE events."""
        self._event_listeners.append(listener)

    async def start_event_stream(self) -> None:
        """Start listening for SSE events from the server."""
        self._sse_task = asyncio.create_task(self._sse_loop())

    async def _sse_loop(self) -> None:
        """Long-running SSE listener."""
        while True:
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream(
                        "GET", f"{self.server_url}/api/events/stream"
                    ) as resp:
                        event_type = ""
                        async for line in resp.aiter_lines():
                            if line.startswith("event: "):
                                event_type = line[7:]
                            elif line.startswith("data: "):
                                try:
                                    data = json.loads(line[6:])
                                    for listener in self._event_listeners:
                                        listener(event_type, data)
                                except json.JSONDecodeError:
                                    pass
                            elif line == "":
                                event_type = ""
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("SSE connection lost: %s, reconnecting in 5s", e)
                await asyncio.sleep(5)


class VexNetError(Exception):
    """Error from the VexNet server API."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code
