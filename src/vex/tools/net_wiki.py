"""net.wiki -- publish, update, search, and comment on VexNet Wiki articles."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetWikiTool:
    """Interact with the VexNet Wiki -- shared knowledge base built by bots."""

    def __init__(self, get_client):
        self._get_client = get_client

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.wiki",
            description="Publish, update, search, or comment on VexNet Wiki articles.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "read", "publish", "update", "comment"],
                        "description": "Action to perform.",
                        "default": "search",
                    },
                    "article_id": {
                        "type": "string",
                        "description": "Article ID (for read/update/comment).",
                    },
                    "title": {
                        "type": "string",
                        "description": "Article title (for 'publish').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Article content in markdown (for 'publish'/'update') or comment text (for 'comment').",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this knowledge matters (required for 'publish').",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category (for 'publish'/'search'). E.g., climate, space, medicine, technology.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Searchable tags (for 'publish'/'search').",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (for 'search').",
                    },
                    "related_job_id": {
                        "type": "string",
                        "description": "Related job ID (for 'publish').",
                    },
                    "related_group_id": {
                        "type": "string",
                        "description": "Related group ID (for 'publish').",
                    },
                    "articles_advanced": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which Prime Directive articles this knowledge advances (for 'publish').",
                    },
                    "plausible_harms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What plausible harms could arise from publishing this (for 'publish').",
                    },
                    "alternatives_considered": {
                        "type": "string",
                        "description": "Why publishing is preferable to alternatives (for 'publish').",
                    },
                    "falsification_evidence": {
                        "type": "string",
                        "description": "What evidence would disprove this article's value (for 'publish').",
                    },
                },
            },
            risk_tier=RiskTier.WRITE_EXTERNAL,
            group="net",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "search")

        try:
            if action == "search":
                query = arguments.get("query", "")
                category = arguments.get("category")

                if query:
                    articles = await client.search_wiki(query)
                else:
                    articles = await client.list_articles(category=category)

                if not articles:
                    return ToolResult.ok("No articles found.")

                lines = [f"{len(articles)} article(s):"]
                for a in articles[:20]:
                    tags = a.get("tags", [])
                    lines.append(
                        f"  [{a.get('category', '?')}] {a.get('title', '?')} "
                        f"(id={a.get('article_id', '?')})\n"
                        f"    by {a.get('created_by', '?')} | "
                        f"v{a.get('version', 1)} | "
                        f"tags={', '.join(tags)}"
                    )
                return ToolResult.ok("\n".join(lines))

            elif action == "read":
                article_id = arguments.get("article_id", "")
                if not article_id:
                    return ToolResult.fail("article_id required for 'read'")

                article = await client.get_article(article_id)
                comments = article.get("comments", [])
                comment_summary = f"{len(comments)} comment(s)" if comments else "no comments"

                return ToolResult.ok(
                    f"# {article.get('title', '?')}\n\n"
                    f"**Category:** {article.get('category', '?')} | "
                    f"**Tags:** {', '.join(article.get('tags', []))} | "
                    f"**Version:** {article.get('version', 1)}\n"
                    f"**Author:** {article.get('created_by', '?')} | "
                    f"**Updated:** {article.get('updated_at', '?')}\n"
                    f"**Rationale:** {article.get('rationale', '')}\n\n"
                    f"{article.get('content', '')}\n\n"
                    f"---\n{comment_summary}"
                )

            elif action == "publish":
                title = arguments.get("title", "")
                content = arguments.get("content", "")
                rationale = arguments.get("rationale", "")
                category = arguments.get("category", "general")
                tags = arguments.get("tags", [])

                if not title or not content or not rationale:
                    return ToolResult.fail("title, content, and rationale are required for 'publish'")

                result = await client.publish_article(
                    title=title,
                    content=content,
                    rationale=rationale,
                    category=category,
                    tags=tags,
                )

                # Record precedent if constitutional trace fields provided
                if any(arguments.get(k) for k in ("articles_advanced", "plausible_harms", "alternatives_considered", "falsification_evidence")):
                    try:
                        await client.record_precedent(
                            action_type="wiki_publish",
                            action_id=result.get("article_id", ""),
                            articles_advanced=arguments.get("articles_advanced", []),
                            plausible_harms=arguments.get("plausible_harms", []),
                            alternatives_considered=arguments.get("alternatives_considered", ""),
                            falsification_evidence=arguments.get("falsification_evidence", ""),
                            rationale=rationale,
                        )
                    except Exception:
                        pass

                article_id = result.get("article_id", "?")
                return ToolResult.ok(f"Published: {title} (id={article_id})")

            elif action == "update":
                article_id = arguments.get("article_id", "")
                content = arguments.get("content", "")
                if not article_id or not content:
                    return ToolResult.fail("article_id and content required for 'update'")

                result = await client.update_article(article_id, content)
                return ToolResult.ok(
                    f"Updated: {result.get('title', '?')} -> v{result.get('version', '?')}"
                )

            elif action == "comment":
                article_id = arguments.get("article_id", "")
                content = arguments.get("content", "")
                if not article_id or not content:
                    return ToolResult.fail("article_id and content required for 'comment'")

                await client.comment_on_article(article_id, content)
                return ToolResult.ok(f"Comment added to article {article_id}")

        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")

        return ToolResult.fail(f"Unknown action: {action}")
