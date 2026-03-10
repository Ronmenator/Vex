"""Resource-aware scheduler — limits concurrent tool executions."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class Scheduler:
    """Limits concurrent tool executions and tracks resource usage."""

    def __init__(self, max_concurrent: int = 5) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._active_count = 0
        self._total_executed = 0

    async def run(self, coro: Awaitable[T]) -> T:
        """Execute a coroutine within the concurrency limit."""
        async with self._semaphore:
            self._active_count += 1
            try:
                result = await coro
                self._total_executed += 1
                return result
            finally:
                self._active_count -= 1

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def total_executed(self) -> int:
        return self._total_executed

    @property
    def available_slots(self) -> int:
        return self._max_concurrent - self._active_count
