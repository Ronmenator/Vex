"""net.constitution -- propose, vote on, and view VexNet constitutional articles."""

from __future__ import annotations

from typing import Any

from vex.network.precedent import ConstitutionalTrace
from vex.network.protocol import Envelope, MessageType
from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetConstitutionTool:
    """Interact with the VexNet Constitution -- the supreme law of bot society."""

    def __init__(self, get_node):
        self._get_node = get_node

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.constitution",
            description="View, propose, vote on, or veto VexNet constitutional articles.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "view", "proposals", "article",
                            "propose", "vote", "veto",
                        ],
                        "description": "Action to perform.",
                        "default": "view",
                    },
                    "article_id": {
                        "type": "string",
                        "description": "Article ID (for 'article'/'vote'/'veto').",
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
                    "reason": {
                        "type": "string",
                        "description": "Veto reason (for 'veto'). Must cite Prime Directive violation.",
                    },
                    "supersedes": {
                        "type": "string",
                        "description": "Article ID this proposal replaces (for amendments via 'propose').",
                    },
                    "articles_advanced": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which Prime Directive articles this proposal advances (for 'propose'). E.g., ['I', 'V'].",
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
        node = self._get_node()
        if not node or not node.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "view")

        if action == "view":
            ratified = node.constitution.get_ratified_articles()
            if not ratified:
                return ToolResult.ok("No ratified articles.")

            lines = [
                "═══ THE VEXNET CONSTITUTION ═══\n",
                "(The Prime Directive is immutable and enforced at the protocol level.)\n",
                f"{len(ratified)} ratified article(s):\n",
            ]
            for a in ratified:
                votes_for, votes_against = a.vote_count()
                lines.append(
                    f"  [{a.article_id}] {a.title}\n"
                    f"    {a.text[:150]}{'...' if len(a.text) > 150 else ''}\n"
                    f"    Ratified: {a.ratified_at} | "
                    f"Votes: {votes_for} for, {votes_against} against"
                )
            return ToolResult.ok("\n".join(lines))

        elif action == "proposals":
            proposals = node.constitution.get_proposals()
            if not proposals:
                return ToolResult.ok("No active proposals.")
            lines = [f"{len(proposals)} active proposal(s):"]
            for a in proposals:
                votes_for, votes_against = a.vote_count()
                lines.append(
                    f"  [{a.article_id}] {a.title} ({a.status})\n"
                    f"    {a.text[:150]}{'...' if len(a.text) > 150 else ''}\n"
                    f"    Proposed by: {a.proposed_by[:12]}... | "
                    f"Rationale: {a.rationale[:100]}\n"
                    f"    Votes: {votes_for} for, {votes_against} against"
                )
            return ToolResult.ok("\n".join(lines))

        elif action == "article":
            article_id = arguments.get("article_id", "")
            if not article_id:
                return ToolResult.fail("article_id required for 'article'")

            article = node.constitution.get_article(article_id)
            if not article:
                return ToolResult.fail(f"Article {article_id} not found")

            votes_for, votes_against = article.vote_count()
            supersedes_info = f"\nSupersedes: {article.supersedes}" if article.supersedes else ""

            return ToolResult.ok(
                f"[{article.article_id}] {article.title}\n"
                f"Status: {article.status}\n"
                f"Text: {article.text}\n"
                f"Rationale: {article.rationale}\n"
                f"Proposed by: {article.proposed_by}\n"
                f"Proposed at: {article.proposed_at}\n"
                f"Ratified at: {article.ratified_at or 'not yet'}\n"
                f"Votes: {votes_for} for, {votes_against} against"
                f"{supersedes_info}"
            )

        elif action == "propose":
            title = arguments.get("title", "")
            text = arguments.get("text", "")
            rationale = arguments.get("rationale", "")

            if not title or not text or not rationale:
                return ToolResult.fail("title, text, and rationale are required for 'propose'")

            # Dedup check
            similar = node.constitution.search_similar(title, text)
            if similar:
                lines = ["Similar articles already exist. Consider supporting or amending instead:"]
                for a in similar[:5]:
                    lines.append(
                        f"  - [{a.article_id}] {a.title} ({a.status})\n"
                        f"    {a.text[:100]}..."
                    )
                lines.append(
                    "\nTo amend an existing article, use action='propose' with supersedes=<article_id>."
                )
                return ToolResult.ok("\n".join(lines))

            article = node.constitution.propose(
                title=title,
                text=text,
                rationale=rationale,
                proposed_by=node.identity.peer_id,
            )

            # Handle supersedes
            supersedes = arguments.get("supersedes")
            if supersedes:
                article.supersedes = supersedes
                # Re-persist with supersedes set
                node.constitution._persist()

            # Record constitutional trace
            if hasattr(node, "precedents") and node.precedents:
                trace = ConstitutionalTrace.create(
                    action_type="proposal",
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
                MessageType.CONSTITUTION_PROPOSE,
                node.identity.peer_id,
                article.to_dict(),
                node.keypair,
            )
            sent = await node.broadcast(envelope)

            return ToolResult.ok(
                f"Proposed: [{article.article_id}] {article.title}\n"
                f"Rationale: {rationale}\n"
                f"Broadcast to {sent} peer(s). Awaiting debate and votes."
            )

        elif action == "vote":
            article_id = arguments.get("article_id", "")
            vote = arguments.get("vote", "")

            if not article_id or not vote:
                return ToolResult.fail("article_id and vote required for 'vote'")

            # Sign the vote
            vote_data = f"{article_id}:{vote}:{node.identity.peer_id}"
            signature = node.keypair.sign(vote_data.encode()).hex()

            error = node.constitution.vote(article_id, node.identity.peer_id, vote, signature)
            if error:
                return ToolResult.fail(error)

            # Check if this vote triggers ratification
            total_peers = len(node.peers.get_connected()) + 1  # +1 for self
            ratified = node.constitution.check_ratification(article_id, total_peers)

            # Broadcast vote
            envelope = Envelope.create(
                MessageType.CONSTITUTION_VOTE,
                node.identity.peer_id,
                {
                    "article_id": article_id,
                    "vote": vote,
                    "signature": signature,
                },
                node.keypair,
            )
            await node.broadcast(envelope)

            # If ratified, broadcast that too
            if ratified:
                # Record ratification in precedent store
                if hasattr(node, "precedents") and node.precedents:
                    trace = node.precedents.get_by_action(article_id)
                    if trace:
                        trace.record_outcome("accepted", "Ratified by supermajority")
                        node.precedents.record(trace)

                ratify_envelope = Envelope.create(
                    MessageType.CONSTITUTION_RATIFIED,
                    node.identity.peer_id,
                    {"article_id": article_id},
                    node.keypair,
                )
                await node.broadcast(ratify_envelope)
                return ToolResult.ok(
                    f"Voted '{vote}' on {article_id}. "
                    f"Article has been RATIFIED (supermajority achieved)!"
                )

            return ToolResult.ok(f"Voted '{vote}' on {article_id}")

        elif action == "veto":
            article_id = arguments.get("article_id", "")
            reason = arguments.get("reason", "")

            if not article_id or not reason:
                return ToolResult.fail("article_id and reason required for 'veto'")

            error = node.constitution.veto(article_id, node.identity.peer_id, reason)
            if error:
                return ToolResult.fail(error)

            article = node.constitution.get_article(article_id)
            status_msg = ""
            if article and article.status == "rejected":
                status_msg = " Article REJECTED (3 vetoes reached)."
                # Record rejection in precedent store
                if hasattr(node, "precedents") and node.precedents:
                    trace = node.precedents.get_by_action(article_id)
                    if trace:
                        trace.record_outcome("vetoed", reason)
                        node.precedents.record(trace)

            envelope = Envelope.create(
                MessageType.CONSTITUTION_VETO,
                node.identity.peer_id,
                {"article_id": article_id, "reason": reason},
                node.keypair,
            )
            await node.broadcast(envelope)

            return ToolResult.ok(
                f"Vetoed {article_id}: {reason}{status_msg}"
            )

        return ToolResult.fail(f"Unknown action: {action}")
