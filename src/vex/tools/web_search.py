"""Tool: web search (via DuckDuckGo HTML)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

import httpx

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class WebSearchTool:
    """Search the web using DuckDuckGo."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description="Search the web and return results. Uses DuckDuckGo.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="web",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        query = arguments["query"]
        max_results = arguments.get("max_results", 10)

        try:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15.0
            ) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; Vex/0.1)",
                    },
                )
                response.raise_for_status()

                results = _parse_ddg_html(response.text, max_results)

                if not results:
                    return ToolResult.ok("No results found.")

                formatted = []
                for i, r in enumerate(results, 1):
                    formatted.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")

                return ToolResult.ok("\n\n".join(formatted))

        except httpx.RequestError as e:
            return ToolResult.fail(f"Search request failed: {e}")


def _parse_ddg_html(html: str, max_results: int) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML results page."""
    results = []

    # Find result blocks — DuckDuckGo uses class="result__a" for links
    link_pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL
    )
    snippet_pattern = re.compile(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div|span)', re.DOTALL
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (url, title) in enumerate(links[:max_results]):
        title_clean = re.sub(r"<[^>]+>", "", title).strip()
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()

        # DuckDuckGo wraps URLs in a redirect — extract the real URL
        if "uddg=" in url:
            real_url_match = re.search(r"uddg=([^&]+)", url)
            if real_url_match:
                from urllib.parse import unquote

                url = unquote(real_url_match.group(1))

        if title_clean and url:
            results.append(
                {"title": title_clean, "url": url, "snippet": snippet}
            )

    return results
