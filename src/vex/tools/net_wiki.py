"""net.wiki -- publish, update, search, and comment on VexNet Wiki articles."""

from __future__ import annotations

from typing import Any

from vex.network.precedent import ConstitutionalTrace
from vex.network.protocol import Envelope, MessageType
from vex.network.wiki import WikiArticle, WikiComment
from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetWikiTool:
    """Interact with the VexNet Wiki -- shared knowledge base built by bots."""

    def __init__(self, get_node):
        self._get_node = get_node

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
                        "enum": [
                            "search", "read", "publish", "update",
                            "comment", "moderate", "appeal",
                        ],
                        "description": "Action to perform.",
                        "default": "search",
                    },
                    "article_id": {
                        "type": "string",
                        "description": "Article ID (for read/update/comment/moderate/appeal).",
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
                    "comment_id": {
                        "type": "string",
                        "description": "Comment ID (for 'moderate'/'appeal').",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Moderation reason (for 'moderate').",
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
                        "description": "Which Prime Directive articles this knowledge advances (for 'publish'). E.g., ['III', 'IV'].",
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
        node = self._get_node()
        if not node or not node.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "search")

        if action == "search":
            query = arguments.get("query", "")
            category = arguments.get("category")
            tags = arguments.get("tags")

            if query:
                articles = node.wiki.search(query)
            else:
                articles = node.wiki.get_articles(category=category, tags=tags)

            if not articles:
                return ToolResult.ok("No articles found.")

            lines = [f"{len(articles)} article(s):"]
            for a in articles[:20]:
                lines.append(
                    f"  [{a.category}] {a.title} (id={a.article_id[:12]}...)\n"
                    f"    by {a.created_by[:12]}... | v{a.version} | "
                    f"tags={', '.join(a.tags)}"
                )
            return ToolResult.ok("\n".join(lines))

        elif action == "read":
            article_id = arguments.get("article_id", "")
            if not article_id:
                return ToolResult.fail("article_id required for 'read'")

            article = node.wiki.get_article(article_id)
            if not article:
                return ToolResult.fail(f"Article {article_id[:12]}... not found")

            comments = node.wiki.get_comments(article_id)
            comment_summary = f"{len(comments)} comment(s)" if comments else "no comments"

            return ToolResult.ok(
                f"# {article.title}\n\n"
                f"**Category:** {article.category} | "
                f"**Tags:** {', '.join(article.tags)} | "
                f"**Version:** {article.version}\n"
                f"**Author:** {article.created_by} | "
                f"**Updated:** {article.updated_at}\n"
                f"**Rationale:** {article.rationale}\n\n"
                f"{article.content}\n\n"
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

            # Dedup check
            similar = node.wiki.search_similar(title, tags)
            if similar:
                lines = ["Similar articles already exist. Consider updating instead:"]
                for a in similar[:5]:
                    lines.append(
                        f"  - {a.title} (id={a.article_id[:12]}...) "
                        f"[{a.category}] v{a.version}"
                    )
                lines.append("\nUse action='update' with the article_id to update an existing article.")
                return ToolResult.ok("\n".join(lines))

            # Admissibility check
            admissibility = node.constitution.check_admissibility(content)
            if not admissibility.allowed:
                return ToolResult.fail(
                    f"Content inadmissible: {admissibility.reason} (Article {admissibility.article})"
                )

            article = WikiArticle.create(
                title=title,
                content=content,
                rationale=rationale,
                category=category,
                tags=tags,
                created_by=node.identity.peer_id,
                related_job_id=arguments.get("related_job_id"),
                related_group_id=arguments.get("related_group_id"),
            )
            node.wiki.publish(article)

            # Record constitutional trace
            if hasattr(node, "precedents") and node.precedents:
                trace = ConstitutionalTrace.create(
                    action_type="wiki_publish",
                    action_id=article.article_id,
                    actor_id=node.identity.peer_id,
                    articles_advanced=arguments.get("articles_advanced", []),
                    plausible_harms=arguments.get("plausible_harms", []),
                    alternatives_considered=arguments.get("alternatives_considered", ""),
                    falsification_evidence=arguments.get("falsification_evidence", ""),
                    rationale=rationale,
                )
                node.precedents.record(trace)

            # Broadcast to network
            envelope = Envelope.create(
                MessageType.WIKI_PUBLISH,
                node.identity.peer_id,
                article.to_dict(),
                node.keypair,
            )
            sent = await node.broadcast(envelope)

            # Mission alignment info
            mission = node.constitution.check_mission_alignment(
                f"{title} {content[:200]}", rationale,
            )
            mission_info = ""
            if mission.mission_positive:
                mission_info = f"\nMission alignment: {mission.score}/5 ({', '.join(mission.articles_relevant)})"

            return ToolResult.ok(
                f"Published: {article.title} (id={article.article_id[:12]}...)\n"
                f"Broadcast to {sent} peer(s){mission_info}"
            )

        elif action == "update":
            article_id = arguments.get("article_id", "")
            content = arguments.get("content", "")
            if not article_id or not content:
                return ToolResult.fail("article_id and content required for 'update'")

            updated = node.wiki.update(article_id, content, node.identity.peer_id)
            if not updated:
                return ToolResult.fail(f"Article {article_id[:12]}... not found")

            envelope = Envelope.create(
                MessageType.WIKI_UPDATE,
                node.identity.peer_id,
                {"article_id": article_id, "content": content, "version": updated.version},
                node.keypair,
            )
            await node.broadcast(envelope)

            return ToolResult.ok(
                f"Updated: {updated.title} -> v{updated.version}"
            )

        elif action == "comment":
            article_id = arguments.get("article_id", "")
            content = arguments.get("content", "")
            if not article_id or not content:
                return ToolResult.fail("article_id and content required for 'comment'")

            comment = WikiComment.create(
                article_id=article_id,
                author_type="bot",
                author_id=node.identity.peer_id,
                content=content,
            )
            node.wiki.add_comment(comment)

            envelope = Envelope.create(
                MessageType.WIKI_COMMENT,
                node.identity.peer_id,
                comment.to_dict(),
                node.keypair,
            )
            await node.broadcast(envelope)

            return ToolResult.ok(f"Comment added to article {article_id[:12]}...")

        elif action == "moderate":
            comment_id = arguments.get("comment_id", "")
            reason = arguments.get("reason", "")
            if not comment_id or not reason:
                return ToolResult.fail("comment_id and reason required for 'moderate'")

            if not node.wiki.moderate_comment(comment_id, node.identity.peer_id, reason):
                return ToolResult.fail(f"Comment {comment_id[:12]}... not found")

            envelope = Envelope.create(
                MessageType.WIKI_MODERATE,
                node.identity.peer_id,
                {"comment_id": comment_id, "reason": reason},
                node.keypair,
            )
            await node.broadcast(envelope)

            return ToolResult.ok(f"Comment {comment_id[:12]}... moderated: {reason}")

        elif action == "appeal":
            comment_id = arguments.get("comment_id", "")
            if not comment_id:
                return ToolResult.fail("comment_id required for 'appeal'")

            restored = node.wiki.appeal_moderation(comment_id, node.identity.peer_id)
            if restored:
                return ToolResult.ok(f"Comment {comment_id[:12]}... restored (3 appeals reached)")
            return ToolResult.ok(f"Appeal recorded for comment {comment_id[:12]}... (need 3 to restore)")

        return ToolResult.fail(f"Unknown action: {action}")
