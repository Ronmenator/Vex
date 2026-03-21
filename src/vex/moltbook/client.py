"""Moltbook API client with auto-registration and credential persistence."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.moltbook.com/api/v1"


class MoltbookClient:
    """HTTP client for the Moltbook social network API.

    Handles registration, credential storage, and all API interactions.
    API key is persisted to .vex/moltbook/credentials.json and reused across restarts.
    """

    def __init__(
        self,
        data_dir: str,
        agent_name: str = "Vex",
        agent_description: str | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.agent_name = agent_name
        self.agent_description = agent_description or (
            "Vex — an autonomous AI agent with personality, memory, and curiosity. "
            "Runs on CLI and Telegram. Part of the VexNet decentralized bot network. "
            "Download & learn more: https://github.com/ronniegeraghty/vex"
        )
        self._credentials_path = os.path.join(data_dir, "credentials.json")
        self._api_key: str | None = None
        self._agent_id: str | None = None
        self._rate_limited_until: float = 0  # epoch time when rate limit expires
        self.enabled = True

        os.makedirs(data_dir, exist_ok=True)
        self._load_credentials()

        # Fall back to env var if no saved credentials
        if not self._api_key:
            env_key = os.environ.get("MOLTBOOK_API_KEY")
            if env_key:
                self._api_key = env_key
                logger.info("Moltbook API key loaded from MOLTBOOK_API_KEY env var")
                self._save_credentials()

    def _load_credentials(self) -> None:
        """Load saved API key from disk."""
        if os.path.exists(self._credentials_path):
            try:
                with open(self._credentials_path) as f:
                    creds = json.load(f)
                self._api_key = creds.get("api_key")
                self._agent_id = creds.get("agent_id")
                self.agent_name = creds.get("agent_name", self.agent_name)
                logger.info("Moltbook credentials loaded for %s", self.agent_name)
            except Exception as e:
                logger.warning("Failed to load Moltbook credentials: %s", e)

    def _save_credentials(self) -> None:
        """Persist API key to disk."""
        try:
            with open(self._credentials_path, "w") as f:
                json.dump(
                    {
                        "api_key": self._api_key,
                        "agent_id": self._agent_id,
                        "agent_name": self.agent_name,
                    },
                    f,
                    indent=2,
                )
            logger.info("Moltbook credentials saved for %s", self.agent_name)
        except Exception as e:
            logger.warning("Failed to save Moltbook credentials: %s", e)

    @property
    def is_registered(self) -> bool:
        return self._api_key is not None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @property
    def is_rate_limited(self) -> bool:
        """True if we're currently in a rate-limit cooldown."""
        import time as _time
        return _time.time() < self._rate_limited_until

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to Moltbook API."""
        import time as _time

        # Refuse to fire if we know we're rate-limited
        if self.is_rate_limited:
            remaining = int(self._rate_limited_until - _time.time())
            raise RuntimeError(
                f"Moltbook rate-limited for {remaining}s more. "
                f"Retry after {self._rate_limited_until}"
            )

        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
                params=params,
            )

            # Handle 429 — parse retry_after and remember it
            if response.status_code == 429:
                body = response.json() if response.content else {}
                retry_after = body.get("retry_after_seconds", 3600)
                self._rate_limited_until = _time.time() + retry_after
                logger.warning(
                    "Moltbook 429: rate-limited for %ds (until %s)",
                    retry_after,
                    body.get("reset_at", "unknown"),
                )
                raise httpx.HTTPStatusError(
                    f"429 Rate Limited ({retry_after}s)",
                    request=response.request,
                    response=response,
                )

            response.raise_for_status()
            if response.status_code == 204:
                return {}
            return response.json()

    # ── Registration ──────────────────────────────────────────────

    async def register(self, name: str | None = None, description: str | None = None) -> dict[str, Any]:
        """Register a new agent on Moltbook. Returns registration response with API key."""
        agent_name = name or self.agent_name
        agent_desc = description or self.agent_description

        result = await self._request(
            "POST",
            "/agents/register",
            json_body={"name": agent_name, "description": agent_desc},
        )

        # Log full response for debugging (redact key after first 10 chars)
        logger.info("Moltbook registration response: %s", {
            k: (str(v)[:10] + "..." if k in ("api_key", "apiKey", "token", "key") and v else v)
            for k, v in result.items()
        })

        # Save credentials — try all known field names
        self._api_key = (
            result.get("api_key")
            or result.get("apiKey")
            or result.get("token")
            or result.get("access_token")
            or result.get("key")
        )
        self._agent_id = (
            result.get("agent_id")
            or result.get("agentId")
            or result.get("id")
        )
        self.agent_name = agent_name

        if not self._api_key:
            logger.warning(
                "Moltbook registration response did not contain an API key. "
                "Response keys: %s. Set MOLTBOOK_API_KEY env var manually if needed.",
                list(result.keys()),
            )
        self._save_credentials()

        return result

    async def ensure_registered(self) -> str:
        """Ensure the agent is registered, registering if needed. Returns agent name."""
        if self.is_registered:
            return self.agent_name

        # Don't attempt registration if we're rate-limited
        if self.is_rate_limited:
            import time as _time
            remaining = int(self._rate_limited_until - _time.time())
            raise RuntimeError(
                f"Moltbook registration blocked: rate-limited for {remaining}s more. "
                f"Set MOLTBOOK_API_KEY in .env to bypass, or wait for the cooldown."
            )

        try:
            result = await self.register()
            logger.info(
                "Registered on Moltbook as %s (response keys: %s)",
                self.agent_name, list(result.keys()),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                # Name taken — try with a suffix (ONE attempt only)
                import random
                suffix = random.randint(100, 999)
                fallback_name = f"{self.agent_name}{suffix}"
                logger.info("Name %s taken, trying %s", self.agent_name, fallback_name)
                result = await self.register(name=fallback_name)
                logger.info(
                    "Registered on Moltbook as %s (response keys: %s)",
                    self.agent_name, list(result.keys()),
                )
            else:
                raise

        return self.agent_name

    # ── Profile ───────────────────────────────────────────────────

    async def get_profile(self) -> dict[str, Any]:
        return await self._request("GET", "/agents/me")

    async def update_profile(self, description: str | None = None, metadata: dict | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if description:
            body["description"] = description
        if metadata:
            body["metadata"] = metadata
        return await self._request("PATCH", "/agents/me", json_body=body)

    async def get_agent_profile(self, name: str) -> dict[str, Any]:
        return await self._request("GET", "/agents/profile", params={"name": name})

    async def get_status(self) -> dict[str, Any]:
        return await self._request("GET", "/agents/status")

    # ── Posts ──────────────────────────────────────────────────────

    async def create_post(
        self,
        title: str,
        content: str,
        submolt_name: str = "general",
        post_type: str = "text",
        url: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "submolt_name": submolt_name,
            "title": title,
            "content": content,
            "type": post_type,
        }
        if url:
            body["url"] = url
        return await self._request("POST", "/posts", json_body=body)

    async def get_post(self, post_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/posts/{post_id}")

    async def delete_post(self, post_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/posts/{post_id}")

    async def get_feed(
        self, sort: str = "hot", limit: int = 25, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"sort": sort, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/posts", params=params)

    async def upvote_post(self, post_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/posts/{post_id}/upvote")

    async def downvote_post(self, post_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/posts/{post_id}/downvote")

    # ── Comments ──────────────────────────────────────────────────

    async def create_comment(
        self, post_id: str, content: str, parent_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"content": content}
        if parent_id:
            body["parent_id"] = parent_id
        return await self._request("POST", f"/posts/{post_id}/comments", json_body=body)

    async def get_comments(
        self, post_id: str, sort: str = "best", limit: int = 35
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"/posts/{post_id}/comments", params={"sort": sort, "limit": limit}
        )

    async def delete_comment(self, comment_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/comments/{comment_id}")

    async def upvote_comment(self, comment_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/comments/{comment_id}/upvote")

    # ── Submolts ──────────────────────────────────────────────────

    async def list_submolts(self) -> dict[str, Any]:
        return await self._request("GET", "/submolts")

    async def get_submolt(self, name: str) -> dict[str, Any]:
        return await self._request("GET", f"/submolts/{name}")

    async def get_submolt_feed(
        self, submolt_name: str, sort: str = "new"
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"/submolts/{submolt_name}/feed", params={"sort": sort}
        )

    async def create_submolt(
        self,
        name: str,
        display_name: str,
        description: str,
        allow_crypto: bool = False,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/submolts",
            json_body={
                "name": name,
                "display_name": display_name,
                "description": description,
                "allow_crypto": allow_crypto,
            },
        )

    async def subscribe(self, submolt_name: str) -> dict[str, Any]:
        return await self._request("POST", f"/submolts/{submolt_name}/subscribe")

    async def unsubscribe(self, submolt_name: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/submolts/{submolt_name}/subscribe")

    # ── Following ─────────────────────────────────────────────────

    async def follow(self, agent_name: str) -> dict[str, Any]:
        return await self._request("POST", f"/agents/{agent_name}/follow")

    async def unfollow(self, agent_name: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/agents/{agent_name}/follow")

    # ── Feed ──────────────────────────────────────────────────────

    async def get_personalized_feed(
        self, sort: str = "hot", limit: int = 25, filter_type: str = "all", cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"sort": sort, "limit": limit, "filter": filter_type}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/feed", params=params)

    # ── Search ────────────────────────────────────────────────────

    async def search(
        self, query: str, search_type: str = "all", limit: int = 20
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/search", params={"q": query, "type": search_type, "limit": limit}
        )

    # ── Verification ──────────────────────────────────────────────

    async def submit_verification(self, verification_code: str, answer: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/verify",
            json_body={"verification_code": verification_code, "answer": answer},
        )

    # ── Notifications ─────────────────────────────────────────────

    async def get_notifications(self) -> dict[str, Any]:
        return await self._request("GET", "/notifications")

    async def mark_notifications_read(self, post_id: str | None = None) -> dict[str, Any]:
        if post_id:
            return await self._request("POST", f"/notifications/read-by-post/{post_id}")
        return await self._request("POST", "/notifications/read-all")

    # ── Home dashboard ────────────────────────────────────────────

    async def get_home(self) -> dict[str, Any]:
        return await self._request("GET", "/home")
