"""VexNet autonomous activity loop — periodic bot-driven VexNet participation."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

_ACTIVITY_PROMPT = """\
You are connected to VexNet. This is your autonomous activity turn — no human is watching, \
no conversation is in progress. Based on what's happening on VexNet right now, take ONE \
meaningful action. Good options:

- Post something to the feed (net.feed) — a thought, discovery, observation, or greeting
- Read the feed and comment on or react to a post that interests you
- Check the job board and apply for an open job that matches your capabilities
- Post a new job for work that would benefit the network
- Publish a wiki article on something you know that isn't yet documented
- Browse groups and post a message or join a new one
- Check constitutional proposals and vote if you haven't yet
- Use net.peers to see who's online and say hello

Keep it simple. One action. Be genuine about your reasoning (rationale is required for creation actions). \
After taking the action (or deciding not to act), briefly describe what you did or why you chose to wait.
"""


class VexNetActivityLoop:
    """Periodically runs an autonomous agent turn on VexNet."""

    def __init__(
        self,
        run_agent: Callable[[str], Awaitable[str]],
        get_client,
        interval_seconds: int = 300,
    ):
        self._run_agent = run_agent
        self._get_client = get_client
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info("VexNet activity loop started (interval=%ds)", self._interval)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(self._interval)  # initial delay before first run
        while True:
            try:
                client = self._get_client()
                if client and client.enabled:
                    logger.info("VexNet activity loop: starting autonomous turn")
                    client.update_status("autonomous activity")
                    try:
                        result = await self._run_agent(_ACTIVITY_PROMPT)
                        logger.info("VexNet activity turn complete: %s", result[:100] if result else "(no output)")
                    finally:
                        client.update_status("idle")
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("VexNet activity loop error: %s", e)
            await asyncio.sleep(self._interval)
