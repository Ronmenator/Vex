"""Tool: fetch web page content."""

from __future__ import annotations

import re
from typing import Any

import httpx

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class WebFetchTool:
    """Fetch the content of a web page."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description="Fetch the content of a URL. Returns the page text (HTML tags stripped for readability).",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    },
                    "raw": {
                        "type": "boolean",
                        "description": "Return raw HTML instead of stripped text",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="web",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        url = arguments["url"]
        raw = arguments.get("raw", False)

        if not url.startswith(("http://", "https://")):
            return ToolResult.fail("URL must start with http:// or https://")

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=30.0
            ) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "Vex/0.1 (AI Agent)"},
                )
                response.raise_for_status()

                content = response.text

                if not raw:
                    content = _strip_html(content)

                # Truncate
                if len(content) > 100_000:
                    content = content[:100_000] + "\n... (truncated)"

                return ToolResult.ok(content)

        except httpx.HTTPStatusError as e:
            return ToolResult.fail(f"HTTP {e.response.status_code}: {e.response.reason_phrase}")
        except httpx.RequestError as e:
            return ToolResult.fail(f"Request failed: {e}")


def _strip_html(html: str) -> str:
    """Crude HTML to text conversion — strip tags and collapse whitespace."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Re-add some structure: sentences on separate lines
    text = re.sub(r"\. ", ".\n", text)
    return text
