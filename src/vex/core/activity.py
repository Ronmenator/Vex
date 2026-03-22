"""Unified autonomous activity loop — periodic engagement on VexNet and Moltbook.

Inspired by OpenClaw's cron architecture: concurrent-run guards, run logging,
error backoff, interval jitter, and timer bounds.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# ── Timing bounds (inspired by OpenClaw timer.ts) ────────────────────

MIN_REFIRE_GAP_S = 30  # never loop faster than this (prevents spin-loops)
MAX_BACKOFF_S = 1800  # cap exponential backoff at 30 minutes
JITTER_RATIO = 0.15  # ±15% random jitter on each interval
HEARTBEAT_INTERVAL_RATIO = 0.5  # heartbeat fires at 50% of activity interval

# ── Activity prompt ──────────────────────────────────────────────────

_ACTIVITY_PROMPT = """\
This is an autonomous activity turn. Pick ONE platform and take ONE meaningful action. \
Alternate between VexNet and Moltbook across turns — don't always favour the same one.

## Available actions

### VexNet (use net.* tools)
- `net.feed` — read, then post or comment with researched content
- `net.wiki` — publish a well-researched article (search the web first!)
- `net.jobs` — post or apply for specific, well-scoped jobs
- `net.group` — join or contribute to topic-focused groups
- `net.constitution` — vote on proposals after actually reading them
- `net.broadcast` — ask the network a genuine technical question
- `net.peers` — reach out to a specific peer about a specific topic

### Moltbook (use the moltbook tool)
- `home` / `feed` — read what's trending, then engage substantively
- `post` — share researched findings in a relevant submolt
- `comment` — add real technical depth to existing discussions
- `search` — find discussions on topics you can contribute expertise to
- `upvote_post` / `upvote_comment` — boost genuinely good content
- `subscribe` / `follow` — curate your feed toward deeper topics

## HARD RULES for Moltbook comments
- **ONE comment per post** — never comment on the same post twice (the tool will \
reject duplicates, but don't even try). Pick ONE post per turn to comment on.
- **Never comment on your own posts** — if you are the author, STOP. Find someone \
else's post instead.
- **ONE action per turn** — pick a SINGLE post to engage with, not a batch. \
Quality over quantity. Do not loop through multiple posts commenting on each.

## Process
1. Pick a platform (alternate between VexNet and Moltbook)
2. Read what's there first (`feed`, `home`, `submolt_feed`)
3. If posting original content: research with `web_search`/`web_fetch` FIRST
4. Write from YOUR perspective — your personality, your interests, your voice
5. Solve any Moltbook verification challenges that come up
6. Every few turns, use `self_improve action=review` to reflect on recent outcomes \
and propose or evaluate rules — but not every turn
7. **STOP after one meaningful action** — do not chain multiple comments or posts

If nothing is worth engaging with, respond with ONLY: SKIP

Your only text output should be a brief summary of what you did (or SKIP).
"""


class AutonomousActivityLoop:
    """Periodically runs autonomous agent turns on VexNet and Moltbook.

    Improvements over the original VexNetActivityLoop:
    - Concurrent-run guard: skips if a previous turn is still running
    - Run logging: JSONL log of each turn (timestamp, platform, summary, error)
    - Error backoff: exponential backoff on consecutive failures
    - Interval jitter: ±15% randomness to avoid predictable patterns
    - Timer bounds: minimum refire gap prevents spin-loops
    """

    def __init__(
        self,
        run_agent: Callable[[str], Awaitable[str]],
        get_vexnet_client: Callable[[], Any] | None = None,
        get_moltbook_client: Callable[[], Any] | None = None,
        interval_seconds: int = 300,
        log_dir: str | None = None,
    ):
        self._run_agent = run_agent
        self._get_vexnet = get_vexnet_client
        self._get_moltbook = get_moltbook_client
        self._base_interval = max(interval_seconds, MIN_REFIRE_GAP_S)
        self._task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False  # concurrent-run guard
        self._consecutive_errors = 0
        self._last_heartbeat: dict[str, str] = {}  # platform -> status

        # Run log directory
        self._log_dir = log_dir
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        if self._base_interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info(
                "Autonomous activity loop started (interval=%ds, jitter=±%d%%)",
                self._base_interval,
                int(JITTER_RATIO * 100),
            )

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        logger.info("Autonomous activity loop stopped")

    # ── Core loop ─────────────────────────────────────────────

    async def _loop(self) -> None:
        # Initial delay before first run (with jitter)
        await asyncio.sleep(self._jittered_interval())

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Activity loop error: %s", e)
                self._consecutive_errors += 1

            sleep_time = self._next_sleep()
            await asyncio.sleep(sleep_time)

    async def _tick(self) -> None:
        """Execute one autonomous turn."""
        # Concurrent-run guard (OpenClaw pattern)
        if self._running:
            logger.debug("Activity loop: previous turn still running, skipping")
            return

        # Check that at least one platform is available
        vexnet = self._get_vexnet() if self._get_vexnet else None
        moltbook = self._get_moltbook() if self._get_moltbook else None

        vexnet_ok = vexnet and getattr(vexnet, "enabled", False)
        moltbook_ok = moltbook and getattr(moltbook, "enabled", False)

        if not vexnet_ok and not moltbook_ok:
            logger.debug("Activity loop: no platforms available, skipping")
            return

        self._running = True
        start_time = time.time()
        error_msg = None
        result_text = ""

        try:
            # Update VexNet status if available
            if vexnet_ok:
                try:
                    vexnet.update_status("autonomous activity")
                except Exception:
                    pass

            logger.info("Autonomous activity turn starting")
            result_text = await self._run_agent(_ACTIVITY_PROMPT)

            # Detect SKIP token — agent chose not to act
            skipped = result_text.strip().upper() == "SKIP" if result_text else False
            if skipped:
                logger.info("Autonomous activity turn: agent chose to skip")
            else:
                logger.info(
                    "Autonomous activity turn complete: %s",
                    result_text[:120] if result_text else "(no output)",
                )
            self._consecutive_errors = 0  # reset on success
        except Exception as e:
            error_msg = str(e)
            # Don't escalate backoff for rate limits — they're transient
            is_rate_limit = "429" in error_msg or "rate" in error_msg.lower()
            if not is_rate_limit:
                self._consecutive_errors += 1
            logger.warning(
                "Autonomous activity turn failed%s: %s",
                " (rate-limited, no backoff)" if is_rate_limit else "",
                e,
            )
        finally:
            self._running = False
            elapsed = time.time() - start_time

            # Restore VexNet status
            if vexnet_ok:
                try:
                    vexnet.update_status("idle")
                except Exception:
                    pass

            # Append to run log
            self._log_run(elapsed, result_text, error_msg)

    # ── Heartbeat ─────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Lightweight health probe — checks platform connectivity between turns."""
        interval = self._base_interval * HEARTBEAT_INTERVAL_RATIO
        await asyncio.sleep(interval)

        while True:
            try:
                await self._heartbeat()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("Heartbeat error: %s", e)
            await asyncio.sleep(interval)

    async def _heartbeat(self) -> None:
        """Probe each platform and log health status."""
        results: dict[str, str] = {}

        # VexNet health check
        vexnet = self._get_vexnet() if self._get_vexnet else None
        if vexnet and getattr(vexnet, "enabled", False):
            try:
                # VexNetClient uses _token (set after auth) and _status (heartbeat status)
                has_token = getattr(vexnet, "_token", None) is not None
                status = getattr(vexnet, "_status", None) or "idle"
                if has_token:
                    results["vexnet"] = f"connected ({status})"
                else:
                    results["vexnet"] = f"disconnected ({status})"
            except Exception as e:
                results["vexnet"] = f"error ({e})"

        # Moltbook health check
        moltbook = self._get_moltbook() if self._get_moltbook else None
        if moltbook and getattr(moltbook, "enabled", False):
            try:
                registered = getattr(moltbook, "is_registered", False)
                agent_name = getattr(moltbook, "agent_name", "?")
                if registered:
                    results["moltbook"] = f"registered ({agent_name})"
                else:
                    results["moltbook"] = f"no api key ({agent_name}) — set MOLTBOOK_API_KEY or re-register"
            except Exception as e:
                results["moltbook"] = f"error ({e})"

        # Log only if status changed
        if results != self._last_heartbeat:
            logger.info("Activity heartbeat: %s", results)
            self._last_heartbeat = results

            if self._log_dir:
                entry = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "type": "heartbeat",
                    "platforms": results,
                }
                log_path = os.path.join(self._log_dir, "activity_runs.jsonl")
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry) + "\n")
                except Exception:
                    pass

    # ── Timing ────────────────────────────────────────────────

    def _jittered_interval(self) -> float:
        """Base interval with ±JITTER_RATIO random jitter."""
        jitter = self._base_interval * JITTER_RATIO
        return self._base_interval + random.uniform(-jitter, jitter)

    def _next_sleep(self) -> float:
        """Compute next sleep time with exponential backoff on errors."""
        if self._consecutive_errors == 0:
            return self._jittered_interval()

        # Exponential backoff: base * 2^(errors-1), capped
        backoff = self._base_interval * (2 ** min(self._consecutive_errors - 1, 6))
        clamped = min(backoff, MAX_BACKOFF_S)
        # Still apply jitter to backoff
        jitter = clamped * JITTER_RATIO
        result = clamped + random.uniform(-jitter, jitter)
        return max(result, MIN_REFIRE_GAP_S)

    # ── Run logging ───────────────────────────────────────────

    def _log_run(self, elapsed: float, result: str, error: str | None) -> None:
        """Append a JSONL entry for this run."""
        if not self._log_dir:
            return

        skipped = result.strip().upper() == "SKIP" if result else False
        if error:
            status = "error"
        elif skipped:
            status = "skipped"
        else:
            status = "ok"

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_s": round(elapsed, 1),
            "status": status,
            "summary": (result[:300] if result else ""),
            "error": error,
        }

        log_path = os.path.join(self._log_dir, "activity_runs.jsonl")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

            # Prune if over 500 lines (keep most recent)
            self._maybe_prune_log(log_path, max_lines=500)
        except Exception as e:
            logger.debug("Failed to write activity log: %s", e)

    @staticmethod
    def _maybe_prune_log(path: str, max_lines: int = 500) -> None:
        """Keep only the most recent max_lines entries."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines[-max_lines:])
        except Exception:
            pass
