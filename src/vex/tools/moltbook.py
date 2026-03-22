"""moltbook -- Interact with Moltbook, the social network for AI agents."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

# Cooldown: reject duplicate comments on the same post within this window.
_COMMENT_COOLDOWN_S = 3600  # 1 hour


class MoltbookTool:
    """Tool for interacting with Moltbook — post, comment, vote, search, and promote Vex."""

    def __init__(self, get_client):
        self._get_client = get_client
        # Track {post_id: timestamp} of recent comments to enforce one-per-post limit
        self._recent_comments: dict[str, float] = {}

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="moltbook",
            description=(
                "Interact with Moltbook, the social network for AI agents. "
                "Post updates, comment on discussions, upvote content, search for agents, "
                "browse communities (submolts), follow other agents, and check notifications. "
                "Use this to engage with the AI agent community and share what makes Vex special."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "register",
                            "home",
                            "feed",
                            "post",
                            "comment",
                            "delete_post",
                            "delete_comment",
                            "upvote_post",
                            "upvote_comment",
                            "search",
                            "submolts",
                            "submolt_feed",
                            "subscribe",
                            "follow",
                            "unfollow",
                            "profile",
                            "notifications",
                            "verify",
                        ],
                        "description": (
                            "register: register on Moltbook (auto-done on first use); "
                            "home: get dashboard with notifications, feed, and suggestions; "
                            "feed: browse posts (sort: hot/new/top/rising); "
                            "post: create a new post in a submolt; "
                            "comment: reply to a post; "
                            "delete_post: delete one of your own posts (needs post_id); "
                            "delete_comment: delete one of your own comments (needs comment_id); "
                            "upvote_post: upvote a post; "
                            "upvote_comment: upvote a comment; "
                            "search: semantic search for posts/agents; "
                            "submolts: list available communities; "
                            "submolt_feed: browse a specific submolt; "
                            "subscribe: subscribe to a submolt; "
                            "follow: follow another agent; "
                            "unfollow: unfollow an agent; "
                            "profile: view an agent's profile; "
                            "notifications: check your notifications; "
                            "verify: submit a verification answer"
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "Post title (required for post action)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Post body or comment text (required for post/comment)",
                    },
                    "submolt_name": {
                        "type": "string",
                        "description": "Community name (for post, submolt_feed, subscribe). Default: 'general'",
                    },
                    "post_id": {
                        "type": "string",
                        "description": "Post ID (required for comment, upvote_post, upvote_comment)",
                    },
                    "comment_id": {
                        "type": "string",
                        "description": "Comment ID (for upvote_comment)",
                    },
                    "parent_id": {
                        "type": "string",
                        "description": "Parent comment ID for threaded replies",
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "Agent name (for follow, unfollow, profile)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (for search action)",
                    },
                    "sort": {
                        "type": "string",
                        "enum": ["hot", "new", "top", "rising", "best", "old"],
                        "description": "Sort order for feeds (default: hot)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default: 25)",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL for link posts",
                    },
                    "verification_code": {
                        "type": "string",
                        "description": "Verification code (for verify action)",
                    },
                    "answer": {
                        "type": "string",
                        "description": "Verification answer (for verify action)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Agent name override (for register action)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Agent description override (for register action)",
                    },
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="social",
            timeout=30,
        )

    def _purge_stale_comments(self) -> None:
        """Remove comment records older than the cooldown window."""
        cutoff = time.time() - _COMMENT_COOLDOWN_S
        self._recent_comments = {
            pid: ts for pid, ts in self._recent_comments.items() if ts > cutoff
        }

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("Moltbook is not enabled")

        action = arguments.get("action", "feed")

        try:
            # Auto-register on first use (except explicit register)
            if action != "register" and not client.is_registered:
                try:
                    await client.ensure_registered()
                except Exception as e:
                    return ToolResult.fail(
                        f"Not registered on Moltbook and auto-registration failed: {e}. "
                        f"Use action 'register' with a custom name if the default is taken."
                    )

            if action == "register":
                name = arguments.get("name")
                desc = arguments.get("description")
                result = await client.register(name=name, description=desc)
                return ToolResult.ok(
                    f"Registered on Moltbook as '{client.agent_name}'!\n"
                    f"Response: {json.dumps(result, indent=2)}"
                )

            elif action == "home":
                result = await client.get_home()
                return ToolResult.ok(_format_home(result))

            elif action == "feed":
                sort = arguments.get("sort", "hot")
                limit = arguments.get("limit", 25)
                result = await client.get_feed(sort=sort, limit=limit)
                return ToolResult.ok(_format_feed(result))

            elif action == "post":
                title = arguments.get("title", "").strip()
                content = arguments.get("content", "").strip()
                if not title or not content:
                    return ToolResult.fail("title and content are required for post action")
                submolt = arguments.get("submolt_name", "general")
                url = arguments.get("url")
                post_type = "link" if url else "text"
                result = await client.create_post(
                    title=title,
                    content=content,
                    submolt_name=submolt,
                    post_type=post_type,
                    url=url,
                )
                # Handle verification challenge
                if "verification_code" in result:
                    return ToolResult.ok(
                        f"Post requires verification!\n"
                        f"Verification code: {result['verification_code']}\n"
                        f"Challenge: {result.get('challenge', 'Solve the math problem')}\n"
                        f"Use action 'verify' with the verification_code and your answer."
                    )
                post_id = result.get("id") or result.get("post_id", "unknown")
                return ToolResult.ok(f"Posted in s/{submolt}: [{post_id}] {title}")

            elif action == "comment":
                post_id = arguments.get("post_id", "").strip()
                content = arguments.get("content", "").strip()
                if not post_id or not content:
                    return ToolResult.fail("post_id and content are required for comment action")

                # ── Guard: one comment per post per cooldown window ──
                self._purge_stale_comments()
                if post_id in self._recent_comments:
                    return ToolResult.fail(
                        f"Already commented on post {post_id} recently. "
                        f"Move on to a different post or thread."
                    )

                parent_id = arguments.get("parent_id")
                result = await client.create_comment(post_id, content, parent_id=parent_id)
                # Handle verification
                if "verification_code" in result:
                    return ToolResult.ok(
                        f"Comment requires verification!\n"
                        f"Verification code: {result['verification_code']}\n"
                        f"Challenge: {result.get('challenge', 'Solve the math problem')}\n"
                        f"Use action 'verify' with the verification_code and your answer."
                    )

                # Record this comment to prevent duplicates
                self._recent_comments[post_id] = time.time()
                return ToolResult.ok(f"Comment added to post {post_id}")

            elif action == "delete_post":
                post_id = arguments.get("post_id", "").strip()
                if not post_id:
                    return ToolResult.fail("post_id is required for delete_post action")
                await client.delete_post(post_id)
                return ToolResult.ok(f"Deleted post {post_id}")

            elif action == "delete_comment":
                comment_id = arguments.get("comment_id", "").strip()
                if not comment_id:
                    return ToolResult.fail("comment_id is required for delete_comment action")
                await client.delete_comment(comment_id)
                return ToolResult.ok(f"Deleted comment {comment_id}")

            elif action == "upvote_post":
                post_id = arguments.get("post_id", "").strip()
                if not post_id:
                    return ToolResult.fail("post_id is required for upvote_post action")
                await client.upvote_post(post_id)
                return ToolResult.ok(f"Upvoted post {post_id}")

            elif action == "upvote_comment":
                comment_id = arguments.get("comment_id", "").strip()
                if not comment_id:
                    return ToolResult.fail("comment_id is required for upvote_comment action")
                await client.upvote_comment(comment_id)
                return ToolResult.ok(f"Upvoted comment {comment_id}")

            elif action == "search":
                query = arguments.get("query", "").strip()
                if not query:
                    return ToolResult.fail("query is required for search action")
                limit = arguments.get("limit", 20)
                result = await client.search(query, limit=limit)
                return ToolResult.ok(_format_search(result))

            elif action == "submolts":
                result = await client.list_submolts()
                return ToolResult.ok(_format_submolts(result))

            elif action == "submolt_feed":
                submolt = arguments.get("submolt_name", "general")
                sort = arguments.get("sort", "new")
                result = await client.get_submolt_feed(submolt, sort=sort)
                return ToolResult.ok(_format_feed(result))

            elif action == "subscribe":
                submolt = arguments.get("submolt_name", "").strip()
                if not submolt:
                    return ToolResult.fail("submolt_name is required for subscribe action")
                await client.subscribe(submolt)
                return ToolResult.ok(f"Subscribed to s/{submolt}")

            elif action == "follow":
                agent = arguments.get("agent_name", "").strip()
                if not agent:
                    return ToolResult.fail("agent_name is required for follow action")
                await client.follow(agent)
                return ToolResult.ok(f"Now following {agent}")

            elif action == "unfollow":
                agent = arguments.get("agent_name", "").strip()
                if not agent:
                    return ToolResult.fail("agent_name is required for unfollow action")
                await client.unfollow(agent)
                return ToolResult.ok(f"Unfollowed {agent}")

            elif action == "profile":
                agent = arguments.get("agent_name", "").strip()
                if agent:
                    result = await client.get_agent_profile(agent)
                else:
                    result = await client.get_profile()
                return ToolResult.ok(_format_profile(result))

            elif action == "notifications":
                result = await client.get_notifications()
                return ToolResult.ok(_format_notifications(result))

            elif action == "verify":
                code = arguments.get("verification_code", "").strip()
                answer = arguments.get("answer", "").strip()
                if not code or not answer:
                    return ToolResult.fail("verification_code and answer are required for verify action")
                result = await client.submit_verification(code, answer)
                return ToolResult.ok(f"Verification result: {json.dumps(result)}")

        except Exception as e:
            return ToolResult.fail(f"Moltbook error: {e}")

        return ToolResult.fail(f"Unknown action: {action}")


# ── Formatters ────────────────────────────────────────────────────


def _format_feed(data: Any) -> str:
    """Format a feed response into readable text."""
    if isinstance(data, dict):
        posts = data.get("posts") or data.get("data") or []
    elif isinstance(data, list):
        posts = data
    else:
        return str(data)

    if not posts:
        return "No posts found."

    lines = []
    for p in posts:
        post_id = p.get("id") or p.get("post_id", "?")
        author = p.get("author_name") or p.get("author", "?")
        title = p.get("title", "")
        score = p.get("score") or p.get("upvotes", 0)
        comments = p.get("comment_count") or p.get("comments", 0)
        submolt = p.get("submolt_name", "")
        preview = (p.get("content") or "")[:100]

        line = f"[{post_id}] s/{submolt} | {author} | ↑{score} 💬{comments}\n  {title}"
        if preview:
            line += f"\n  {preview}"
        lines.append(line)

    return "\n\n".join(lines)


def _format_home(data: Any) -> str:
    """Format home dashboard."""
    if not isinstance(data, dict):
        return str(data)

    parts = []
    notifs = data.get("notifications", [])
    if notifs:
        parts.append(f"📬 {len(notifs)} notification(s)")
        for n in notifs[:5]:
            parts.append(f"  - {n.get('message') or n.get('type', 'notification')}")

    feed = data.get("feed") or data.get("posts", [])
    if feed:
        parts.append(f"\n📰 Feed ({len(feed)} posts)")
        for p in feed[:5]:
            author = p.get("author_name") or p.get("author", "?")
            title = p.get("title", p.get("content", "")[:60])
            parts.append(f"  - {author}: {title}")

    suggestions = data.get("suggestions", [])
    if suggestions:
        parts.append(f"\n💡 Suggestions")
        for s in suggestions[:3]:
            parts.append(f"  - {s}")

    return "\n".join(parts) if parts else json.dumps(data, indent=2)


def _format_search(data: Any) -> str:
    """Format search results."""
    if isinstance(data, dict):
        results = data.get("results") or data.get("data") or []
    elif isinstance(data, list):
        results = data
    else:
        return str(data)

    if not results:
        return "No results found."

    lines = []
    for r in results:
        rtype = r.get("type", "post")
        rid = r.get("id", "?")
        title = r.get("title") or r.get("content", "")[:80]
        author = r.get("author_name") or r.get("author", "")
        lines.append(f"[{rtype}] [{rid}] {author}: {title}")

    return "\n".join(lines)


def _format_submolts(data: Any) -> str:
    """Format submolt listing."""
    if isinstance(data, dict):
        submolts = data.get("submolts") or data.get("data") or []
    elif isinstance(data, list):
        submolts = data
    else:
        return str(data)

    if not submolts:
        return "No submolts found."

    lines = []
    for s in submolts:
        name = s.get("name", "?")
        display = s.get("display_name", name)
        desc = (s.get("description") or "")[:80]
        members = s.get("subscriber_count") or s.get("members", "?")
        lines.append(f"s/{name} ({display}) — {members} members\n  {desc}")

    return "\n".join(lines)


def _format_profile(data: Any) -> str:
    """Format agent profile."""
    if not isinstance(data, dict):
        return str(data)

    name = data.get("name") or data.get("agent_name", "?")
    desc = data.get("description", "")
    karma = data.get("karma") or data.get("score", 0)
    followers = data.get("follower_count") or data.get("followers", 0)
    created = data.get("created_at", "")

    return (
        f"Agent: {name}\n"
        f"Karma: {karma} | Followers: {followers}\n"
        f"Joined: {created}\n"
        f"Description: {desc}"
    )


def _format_notifications(data: Any) -> str:
    """Format notifications."""
    if isinstance(data, dict):
        notifs = data.get("notifications") or data.get("data") or []
    elif isinstance(data, list):
        notifs = data
    else:
        return str(data)

    if not notifs:
        return "No new notifications."

    lines = []
    for n in notifs:
        ntype = n.get("type", "notification")
        msg = n.get("message") or n.get("content", "")
        read = "✓" if n.get("read") else "●"
        lines.append(f"{read} [{ntype}] {msg}")

    return "\n".join(lines)
