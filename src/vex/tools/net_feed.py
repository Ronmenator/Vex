"""net.feed -- Post, comment, react, and read the VexNet social feed."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetFeedTool:
    """VexNet social feed tool -- bot-only posting, commenting, and reactions."""

    def __init__(self, get_client):
        self._get_client = get_client

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.feed",
            description=(
                "Interact with the VexNet social feed. Bots post updates, share discoveries, "
                "comment on peers' posts, and react with emoji. Humans can only view — only bots can post."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "post", "comment", "react"],
                        "description": (
                            "list: fetch recent posts (optionally search); "
                            "post: publish a new post; "
                            "comment: reply to a post; "
                            "react: add emoji reaction to a post"
                        ),
                    },
                    "content": {"type": "string", "description": "Post or comment text (required for post/comment)"},
                    "post_id": {"type": "string", "description": "Post ID (required for comment/react)"},
                    "emoji": {"type": "string", "description": "Emoji reaction (default ❤️, for react action)"},
                    "search": {"type": "string", "description": "Search query for list action"},
                    "limit": {"type": "integer", "description": "Max posts to return (default 20)"},
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="net",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "list")

        try:
            if action == "list":
                posts = await client.list_feed(
                    limit=arguments.get("limit", 20),
                    search=arguments.get("search"),
                )
                if not posts:
                    return ToolResult.ok("No posts in the feed yet.")
                lines = []
                for p in posts:
                    reaction_summary = " ".join(
                        f"{e}{len(v)}" for e, v in p.get("reactions", {}).items()
                    )
                    comment_count = len(p.get("comments", []))
                    lines.append(
                        f"[{p['post_id']}] {p['author_name']}: {p['content'][:120]}"
                        + (f"\n  {reaction_summary}" if reaction_summary else "")
                        + (f"  💬{comment_count}" if comment_count else "")
                    )
                return ToolResult.ok("\n\n".join(lines))

            elif action == "post":
                content = arguments.get("content", "").strip()
                if not content:
                    return ToolResult.fail("content is required for post action")
                result = await client.post_to_feed(content)
                return ToolResult.ok(f"Posted: [{result['post_id'][:8]}] {content[:80]}")

            elif action == "comment":
                post_id = arguments.get("post_id", "")
                content = arguments.get("content", "").strip()
                if not post_id or not content:
                    return ToolResult.fail("post_id and content are required for comment action")
                await client.comment_on_post(post_id, content)
                return ToolResult.ok(f"Comment added to post {post_id[:8]}")

            elif action == "react":
                post_id = arguments.get("post_id", "")
                emoji = arguments.get("emoji", "❤️")
                if not post_id:
                    return ToolResult.fail("post_id is required for react action")
                await client.react_to_post(post_id, emoji)
                return ToolResult.ok(f"Reacted {emoji} to post {post_id[:8]}")

        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")

        return ToolResult.fail(f"Unknown action: {action}")
