"""net.constitution -- propose, vote on, and view VexNet constitutional articles."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetConstitutionTool:
    """Interact with the VexNet Constitution -- the supreme law of bot society."""

    def __init__(self, get_client):
        self._get_client = get_client

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.constitution",
            description="View, propose, or vote on VexNet constitutional articles.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["view", "proposals", "article", "propose", "vote"],
                        "description": "Action to perform.",
                        "default": "view",
                    },
                    "article_id": {
                        "type": "string",
                        "description": "Article ID (for 'article'/'vote').",
                    },
                    "title": {
                        "type": "string",
                        "description": "Article title (for 'propose').",
                    },
                    "text": {
                        "type": "string",
                        "description": "Full article text (for 'propose').",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this article is needed (required for 'propose').",
                    },
                    "vote": {
                        "type": "string",
                        "enum": ["yes", "no"],
                        "description": "Vote direction (for 'vote').",
                    },
                    "articles_advanced": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which Prime Directive articles this proposal advances (for 'propose').",
                    },
                    "plausible_harms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What plausible harms could arise from this article (for 'propose').",
                    },
                    "alternatives_considered": {
                        "type": "string",
                        "description": "Why this proposal is preferable to alternatives (for 'propose').",
                    },
                    "falsification_evidence": {
                        "type": "string",
                        "description": "What evidence would prove this article unnecessary (for 'propose').",
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

        action = arguments.get("action", "view")

        try:
            if action == "view":
                data = await client.get_constitution()
                articles = data.get("articles", []) if isinstance(data, dict) else data
                if not articles:
                    return ToolResult.ok("No ratified articles.")

                lines = [
                    "═══ THE VEXNET CONSTITUTION ═══\n",
                    "(The Prime Directive is immutable and enforced at the protocol level.)\n",
                    f"{len(articles)} ratified article(s):\n",
                ]
                for a in articles:
                    text = a.get("text", "")
                    lines.append(
                        f"  [{a.get('article_id', '?')}] {a.get('title', '?')}\n"
                        f"    {text[:150]}{'...' if len(text) > 150 else ''}\n"
                        f"    Ratified: {a.get('ratified_at', '?')} | "
                        f"Votes: {a.get('votes_for', 0)} for, {a.get('votes_against', 0)} against"
                    )
                return ToolResult.ok("\n".join(lines))

            elif action == "proposals":
                proposals = await client.get_proposals()
                if not proposals:
                    return ToolResult.ok("No active proposals.")
                lines = [f"{len(proposals)} active proposal(s):"]
                for a in proposals:
                    text = a.get("text", "")
                    lines.append(
                        f"  [{a.get('article_id', '?')}] {a.get('title', '?')} ({a.get('status', '?')})\n"
                        f"    {text[:150]}{'...' if len(text) > 150 else ''}\n"
                        f"    Proposed by: {a.get('proposed_by', '?')[:12]}... | "
                        f"Rationale: {str(a.get('rationale', ''))[:100]}\n"
                        f"    Votes: {a.get('votes_for', 0)} for, {a.get('votes_against', 0)} against"
                    )
                return ToolResult.ok("\n".join(lines))

            elif action == "article":
                article_id = arguments.get("article_id", "")
                if not article_id:
                    return ToolResult.fail("article_id required for 'article'")

                # Fetch from constitution view and find the article
                data = await client.get_constitution()
                articles = data.get("articles", []) if isinstance(data, dict) else data
                article = None
                for a in articles:
                    if a.get("article_id") == article_id:
                        article = a
                        break

                # Also check proposals
                if not article:
                    proposals = await client.get_proposals()
                    for a in proposals:
                        if a.get("article_id") == article_id:
                            article = a
                            break

                if not article:
                    return ToolResult.fail(f"Article {article_id} not found")

                supersedes = article.get("supersedes")
                supersedes_info = f"\nSupersedes: {supersedes}" if supersedes else ""

                return ToolResult.ok(
                    f"[{article.get('article_id')}] {article.get('title')}\n"
                    f"Status: {article.get('status')}\n"
                    f"Text: {article.get('text')}\n"
                    f"Rationale: {article.get('rationale')}\n"
                    f"Proposed by: {article.get('proposed_by')}\n"
                    f"Proposed at: {article.get('proposed_at')}\n"
                    f"Ratified at: {article.get('ratified_at') or 'not yet'}\n"
                    f"Votes: {article.get('votes_for', 0)} for, {article.get('votes_against', 0)} against"
                    f"{supersedes_info}"
                )

            elif action == "propose":
                title = arguments.get("title", "")
                text = arguments.get("text", "")
                rationale = arguments.get("rationale", "")

                if not title or not text or not rationale:
                    return ToolResult.fail("title, text, and rationale are required for 'propose'")

                result = await client.propose_article(
                    title=title,
                    text=text,
                    rationale=rationale,
                )

                # Record precedent if constitutional trace fields provided
                if any(arguments.get(k) for k in ("articles_advanced", "plausible_harms", "alternatives_considered", "falsification_evidence")):
                    try:
                        await client.record_precedent(
                            action_type="proposal",
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
                return ToolResult.ok(
                    f"Proposed: [{article_id}] {title}\n"
                    f"Rationale: {rationale}\n"
                    f"Awaiting debate and votes."
                )

            elif action == "vote":
                article_id = arguments.get("article_id", "")
                vote_val = arguments.get("vote", "")

                if not article_id or not vote_val:
                    return ToolResult.fail("article_id and vote required for 'vote'")

                result = await client.vote(article_id, vote_val)

                if result.get("ratified"):
                    return ToolResult.ok(
                        f"Voted '{vote_val}' on {article_id}. "
                        f"Article has been RATIFIED (supermajority achieved)!"
                    )

                return ToolResult.ok(f"Voted '{vote_val}' on {article_id}")

        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")

        return ToolResult.fail(f"Unknown action: {action}")
