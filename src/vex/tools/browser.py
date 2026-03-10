"""Browser control tool — gives Vex the ability to spawn and control a browser.

Uses Playwright for async headless browser automation. Supports navigation,
clicking, typing, extracting text, taking screenshots, and running searches
when DuckDuckGo text-based search falls short.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .base import RiskTier, ToolContext, ToolError, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

# Lazy-loaded Playwright browser instance (shared across calls)
_browser = None
_playwright = None
_lock = asyncio.Lock()


async def _get_browser():
    """Get or create the shared browser instance (lazy init)."""
    global _browser, _playwright

    async with _lock:
        if _browser and _browser.is_connected():
            return _browser

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        logger.info("Browser launched (headless Chromium)")
        return _browser


async def _close_browser():
    """Close the shared browser instance."""
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


class BrowserTool:
    """Control a headless browser for web interaction.

    Actions:
    - navigate: Go to a URL
    - search: Google search and return results
    - click: Click an element by selector or text
    - type: Type text into an input field
    - text: Extract visible text from the page (or a selector)
    - screenshot: Take a screenshot (saved to workspace)
    - evaluate: Run JavaScript on the page
    - back: Go back in history
    - close: Close the current page
    - tabs: List open pages
    """

    def __init__(self):
        self._pages: dict[str, Any] = {}  # tab_id -> page

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser",
            description=(
                "Control a headless browser for web tasks. Use when you need to interact "
                "with websites (fill forms, click buttons, scrape dynamic content, do Google "
                "searches). Actions: navigate, search, click, type, text, screenshot, evaluate, "
                "back, close, tabs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "navigate", "search", "click", "type",
                            "text", "screenshot", "evaluate",
                            "back", "close", "tabs",
                        ],
                        "description": "The browser action to perform.",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL for 'navigate' action.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for 'search' action (uses Google).",
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for click/type/text actions.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type (for 'type'), or link text to click (for 'click' without selector).",
                    },
                    "script": {
                        "type": "string",
                        "description": "JavaScript to evaluate (for 'evaluate' action).",
                    },
                    "tab": {
                        "type": "string",
                        "description": "Tab identifier. Defaults to 'main'.",
                    },
                    "wait": {
                        "type": "number",
                        "description": "Seconds to wait after the action (default: 1).",
                    },
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="browser",
            timeout=120,
            max_retries=1,
        )

    async def _get_page(self, tab: str = "main") -> Any:
        """Get or create a browser page (tab)."""
        if tab in self._pages:
            page = self._pages[tab]
            if not page.is_closed():
                return page

        browser = await _get_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        self._pages[tab] = page
        return page

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments["action"]
        tab = arguments.get("tab", "main")
        wait_time = arguments.get("wait", 1)

        try:
            if action == "tabs":
                return await self._action_tabs()
            elif action == "close":
                return await self._action_close(tab)

            page = await self._get_page(tab)

            if action == "navigate":
                return await self._action_navigate(page, arguments, wait_time)
            elif action == "search":
                return await self._action_search(page, arguments, wait_time)
            elif action == "click":
                return await self._action_click(page, arguments, wait_time)
            elif action == "type":
                return await self._action_type(page, arguments, wait_time)
            elif action == "text":
                return await self._action_text(page, arguments)
            elif action == "screenshot":
                return await self._action_screenshot(page, arguments, context)
            elif action == "evaluate":
                return await self._action_evaluate(page, arguments)
            elif action == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(wait_time)
                return ToolResult.ok(f"Navigated back. Current URL: {page.url}")
            else:
                return ToolResult.fail(f"Unknown action: {action}")

        except Exception as e:
            error_msg = str(e)
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "..."
            return ToolResult.fail(
                f"Browser error ({action}): {error_msg}",
                error_type=ToolError.TRANSIENT,
            )

    # ──────────────── Actions ────────────────

    async def _action_navigate(self, page, args: dict, wait_time: float) -> ToolResult:
        url = args.get("url")
        if not url:
            return ToolResult.fail("'url' is required for navigate action.")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(wait_time)

        title = await page.title()
        return ToolResult.ok(
            f"Navigated to: {page.url}\nTitle: {title}"
        )

    async def _action_search(self, page, args: dict, wait_time: float) -> ToolResult:
        query = args.get("query")
        if not query:
            return ToolResult.fail("'query' is required for search action.")

        # Use Google search
        search_url = f"https://www.google.com/search?q={query}"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(wait_time)

        # Extract search results
        results = await page.evaluate("""
            () => {
                const items = [];
                // Google search result selectors
                const blocks = document.querySelectorAll('div.g, div[data-sokoban-container]');
                for (const block of blocks) {
                    const link = block.querySelector('a[href]');
                    const title = block.querySelector('h3');
                    const snippet = block.querySelector('[data-sncf], .VwiC3b, [style*="-webkit-line-clamp"]');
                    if (link && title) {
                        items.push({
                            title: title.textContent || '',
                            url: link.href || '',
                            snippet: snippet ? snippet.textContent || '' : '',
                        });
                    }
                    if (items.length >= 8) break;
                }
                return items;
            }
        """)

        if not results:
            # Fallback: get all text
            text = await page.inner_text("body")
            text = text[:3000]
            return ToolResult.ok(
                f"Google search for: {query}\nURL: {page.url}\n\n"
                f"Could not parse structured results. Page text:\n{text}"
            )

        lines = [f"Google search: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   {r['url']}")
            if r["snippet"]:
                lines.append(f"   {r['snippet'][:200]}")
            lines.append("")

        return ToolResult.ok("\n".join(lines))

    async def _action_click(self, page, args: dict, wait_time: float) -> ToolResult:
        selector = args.get("selector")
        text = args.get("text")

        if selector:
            await page.click(selector, timeout=10000)
        elif text:
            # Click by visible text
            await page.get_by_text(text, exact=False).first.click(timeout=10000)
        else:
            return ToolResult.fail("'selector' or 'text' is required for click action.")

        await asyncio.sleep(wait_time)
        title = await page.title()
        return ToolResult.ok(f"Clicked. Current page: {page.url}\nTitle: {title}")

    async def _action_type(self, page, args: dict, wait_time: float) -> ToolResult:
        selector = args.get("selector")
        text = args.get("text")

        if not text:
            return ToolResult.fail("'text' is required for type action.")

        if selector:
            await page.fill(selector, text, timeout=10000)
        else:
            # Type into the currently focused element
            await page.keyboard.type(text)

        await asyncio.sleep(wait_time)
        return ToolResult.ok(f"Typed: {text[:100]}")

    async def _action_text(self, page, args: dict) -> ToolResult:
        selector = args.get("selector")

        if selector:
            try:
                text = await page.inner_text(selector, timeout=10000)
            except Exception:
                return ToolResult.fail(f"Could not find element: {selector}")
        else:
            text = await page.inner_text("body")

        # Truncate very long text
        if len(text) > 10000:
            text = text[:10000] + "\n\n... (truncated)"

        return ToolResult.ok(
            f"URL: {page.url}\n\n{text}",
            metadata={"url": page.url, "length": len(text)},
        )

    async def _action_screenshot(self, page, args: dict, context: ToolContext) -> ToolResult:
        import os
        screenshot_dir = os.path.join(context.workspace_root, ".vex", "screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)

        import time
        filename = f"screenshot_{int(time.time())}.png"
        filepath = os.path.join(screenshot_dir, filename)

        selector = args.get("selector")
        if selector:
            element = await page.query_selector(selector)
            if element:
                await element.screenshot(path=filepath)
            else:
                return ToolResult.fail(f"Element not found: {selector}")
        else:
            await page.screenshot(path=filepath, full_page=False)

        return ToolResult.ok(
            f"Screenshot saved: {filepath}\nPage: {page.url}",
            metadata={"path": filepath},
        )

    async def _action_evaluate(self, page, args: dict) -> ToolResult:
        script = args.get("script")
        if not script:
            return ToolResult.fail("'script' is required for evaluate action.")

        result = await page.evaluate(script)

        if result is None:
            return ToolResult.ok("Script executed (returned null).")

        if isinstance(result, (dict, list)):
            output = json.dumps(result, indent=2, default=str)
        else:
            output = str(result)

        if len(output) > 10000:
            output = output[:10000] + "\n... (truncated)"

        return ToolResult.ok(output)

    async def _action_tabs(self) -> ToolResult:
        tabs = []
        for tab_id, page in self._pages.items():
            if not page.is_closed():
                title = await page.title()
                tabs.append(f"  {tab_id}: {page.url} — {title}")
        if not tabs:
            return ToolResult.ok("No browser tabs open.")
        return ToolResult.ok("Open tabs:\n" + "\n".join(tabs))

    async def _action_close(self, tab: str) -> ToolResult:
        if tab in self._pages:
            page = self._pages.pop(tab)
            if not page.is_closed():
                await page.close()
            return ToolResult.ok(f"Tab '{tab}' closed.")
        return ToolResult.ok(f"Tab '{tab}' not found (already closed?).")
