"""Tool execution middleware — timeout, retry, resource limits, dry-run."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from .base import Tool, ToolContext, ToolError, ToolResult, ToolSchema


class ToolMiddleware(Protocol):
    """Middleware that wraps tool execution."""

    async def __call__(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        context: ToolContext,
        next_fn: ToolExecuteFn,
    ) -> ToolResult: ...


# Type for the next function in the middleware chain
ToolExecuteFn = Any  # Callable[[Tool, dict, ToolContext], Awaitable[ToolResult]]


class TimeoutMiddleware:
    """Wraps tool execution with a timeout."""

    async def __call__(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        context: ToolContext,
        next_fn: ToolExecuteFn,
    ) -> ToolResult:
        timeout = tool.schema.timeout
        if timeout <= 0:
            return await next_fn(tool, arguments, context)

        try:
            return await asyncio.wait_for(
                next_fn(tool, arguments, context), timeout=timeout
            )
        except asyncio.TimeoutError:
            return ToolResult.fail(
                f"Tool '{tool.schema.name}' timed out after {timeout}s",
                error_type=ToolError.TIMEOUT,
            )


class RetryMiddleware:
    """Retries tool execution on transient errors."""

    async def __call__(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        context: ToolContext,
        next_fn: ToolExecuteFn,
    ) -> ToolResult:
        max_retries = tool.schema.max_retries
        last_result: ToolResult | None = None

        for attempt in range(max_retries + 1):
            result = await next_fn(tool, arguments, context)

            if not result.is_error:
                return result

            last_result = result

            # Only retry transient errors
            if result.error_type != ToolError.TRANSIENT:
                return result

            # Don't sleep on the last attempt
            if attempt < max_retries:
                await asyncio.sleep(min(2**attempt, 10))

        return last_result or ToolResult.fail("Retry exhausted")


class DryRunMiddleware:
    """Skips actual execution in dry-run mode for write/destructive tools."""

    async def __call__(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        context: ToolContext,
        next_fn: ToolExecuteFn,
    ) -> ToolResult:
        from .base import RiskTier

        if context.dry_run and tool.schema.risk_tier >= RiskTier.WRITE_LOCAL:
            args_preview = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
            return ToolResult.ok(
                f"[DRY RUN] Would execute {tool.schema.name}({args_preview})",
                metadata={"dry_run": True},
            )
        return await next_fn(tool, arguments, context)


class MetricsMiddleware:
    """Collects execution timing and success/failure metrics."""

    def __init__(self) -> None:
        self.metrics: list[dict[str, Any]] = []

    async def __call__(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        context: ToolContext,
        next_fn: ToolExecuteFn,
    ) -> ToolResult:
        start = time.monotonic()
        result = await next_fn(tool, arguments, context)
        elapsed = time.monotonic() - start

        self.metrics.append(
            {
                "tool": tool.schema.name,
                "agent_id": context.agent_id,
                "duration_s": round(elapsed, 3),
                "success": not result.is_error,
                "error_type": result.error_type.name if result.error_type else None,
            }
        )
        return result


class ToolExecutor:
    """Chains middleware and executes tools."""

    def __init__(self, middleware: list[Any] | None = None) -> None:
        self._middleware = middleware or []

    def add(self, mw: Any) -> None:
        self._middleware.append(mw)

    async def run(
        self, tool: Tool, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        """Execute a tool through the middleware chain."""

        async def base_execute(
            t: Tool, args: dict[str, Any], ctx: ToolContext
        ) -> ToolResult:
            return await t.execute(args, ctx)

        # Build the chain from innermost (base_execute) outward
        chain = base_execute
        for mw in reversed(self._middleware):

            def make_next(current_mw: Any, next_fn: Any) -> ToolExecuteFn:
                async def wrapped(
                    t: Tool, args: dict[str, Any], ctx: ToolContext
                ) -> ToolResult:
                    return await current_mw(t, args, ctx, next_fn)

                return wrapped

            chain = make_next(mw, chain)

        return await chain(tool, arguments, context)
