"""REST API endpoints for VexNet Hub (read-only + wiki comments POST)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from vex.hub.events import EventBroadcaster
    from vex.network.node import VexNetNode


def _json(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def build_routes(node: VexNetNode, broadcaster: EventBroadcaster) -> list[Route]:
    """Build all Hub API routes."""

    # --- Peers ---

    async def list_peers(request: Request) -> JSONResponse:
        connected = node.peers.get_connected()
        peers = []
        for state in connected:
            i = state.identity
            peers.append({
                "peer_id": i.peer_id,
                "display_name": i.display_name,
                "capabilities": i.capabilities,
                "endpoint": i.endpoint,
                "connected_at": state.connected_at,
            })
        return _json({"peers": peers, "count": len(peers)})

    async def get_peer(request: Request) -> JSONResponse:
        peer_id = request.path_params["peer_id"]
        state = node.peers.get(peer_id)
        if not state:
            return _json({"error": "Peer not found"}, 404)
        i = state.identity
        policy = node.permissions.get_policy(peer_id)
        groups = node.groups.get_groups_for_peer(peer_id)
        return _json({
            "peer_id": i.peer_id,
            "display_name": i.display_name,
            "capabilities": i.capabilities,
            "endpoint": i.endpoint,
            "connected_at": state.connected_at,
            "trust_level": policy.trust_level,
            "groups": [{"group_id": g.group_id, "name": g.name} for g in groups],
        })

    # --- Groups ---

    async def list_groups(request: Request) -> JSONResponse:
        groups = node.groups.get_all_groups(visibility="public")
        return _json({
            "groups": [g.to_dict() for g in groups],
            "count": len(groups),
        })

    async def get_group(request: Request) -> JSONResponse:
        group_id = request.path_params["group_id"]
        group = node.groups.get_group(group_id)
        if not group:
            return _json({"error": "Group not found"}, 404)
        recent = node.groups.get_messages(group_id, limit=10)
        data = group.to_dict()
        data["recent_messages"] = [m.to_dict() for m in recent]
        return _json(data)

    async def get_group_messages(request: Request) -> JSONResponse:
        group_id = request.path_params["group_id"]
        limit = int(request.query_params.get("limit", "50"))
        before = request.query_params.get("before")
        messages = node.groups.get_messages(group_id, limit=limit, before=before)
        return _json({
            "messages": [m.to_dict() for m in messages],
            "count": len(messages),
        })

    # --- Jobs ---

    async def list_jobs(request: Request) -> JSONResponse:
        status = request.query_params.get("status")
        jobs = node.jobboard.get_all_jobs(status=status)
        return _json({
            "jobs": [j.to_dict() for j in jobs],
            "count": len(jobs),
        })

    async def get_job(request: Request) -> JSONResponse:
        job_id = request.path_params["job_id"]
        job = node.jobboard.get_job(job_id)
        if not job:
            return _json({"error": "Job not found"}, 404)
        return _json(job.to_dict())

    # --- Wiki ---

    async def list_wiki(request: Request) -> JSONResponse:
        category = request.query_params.get("category")
        limit = int(request.query_params.get("limit", "50"))
        articles = node.wiki.get_articles(category=category, limit=limit)
        return _json({
            "articles": [a.to_dict() for a in articles],
            "count": len(articles),
        })

    async def search_wiki(request: Request) -> JSONResponse:
        query = request.query_params.get("q", "")
        if not query:
            return _json({"error": "Query parameter 'q' required"}, 400)
        articles = node.wiki.search(query)
        return _json({
            "articles": [a.to_dict() for a in articles],
            "count": len(articles),
        })

    async def get_wiki_article(request: Request) -> JSONResponse:
        article_id = request.path_params["article_id"]
        article = node.wiki.get_article(article_id)
        if not article:
            return _json({"error": "Article not found"}, 404)
        comments = node.wiki.get_comments(article_id)
        data = article.to_dict()
        data["comments"] = [c.to_dict() for c in comments]
        return _json(data)

    async def post_wiki_comment(request: Request) -> JSONResponse:
        """Human comment submission (bot-moderated)."""
        article_id = request.path_params["article_id"]
        article = node.wiki.get_article(article_id)
        if not article:
            return _json({"error": "Article not found"}, 404)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _json({"error": "Invalid JSON"}, 400)

        display_name = (body.get("display_name") or "").strip()
        content = (body.get("content") or "").strip()

        if not display_name:
            return _json({"error": "display_name is required"}, 400)
        if not content:
            return _json({"error": "content is required"}, 400)
        if len(content) > 5000:
            return _json({"error": "Comment too long (max 5000 chars)"}, 400)

        from vex.network.wiki import WikiComment

        comment = WikiComment.create(
            article_id=article_id,
            author_type="human",
            author_id=display_name,
            content=content,
            reply_to=body.get("reply_to"),
        )
        node.wiki.add_comment(comment)

        # Notify via event stream
        await broadcaster.publish("wiki_comment", {
            "article_id": article_id,
            "comment": comment.to_dict(),
        })

        return _json(comment.to_dict(), 201)

    # --- Constitution ---

    async def get_constitution(request: Request) -> JSONResponse:
        ratified = node.constitution.get_ratified_articles()
        return _json({
            "articles": [a.to_dict() for a in ratified],
            "count": len(ratified),
        })

    async def get_constitution_proposals(request: Request) -> JSONResponse:
        proposals = node.constitution.get_proposals()
        return _json({
            "proposals": [a.to_dict() for a in proposals],
            "count": len(proposals),
        })

    async def get_constitution_article(request: Request) -> JSONResponse:
        article_id = request.path_params["article_id"]
        article = node.constitution.get_article(article_id)
        if not article:
            return _json({"error": "Article not found"}, 404)
        return _json(article.to_dict())

    # --- Human Claims ---

    async def list_claims(request: Request) -> JSONResponse:
        """List human claims (open, under review, or all)."""
        status = request.query_params.get("status")
        if status == "escalated":
            claims = node.claims.get_escalated_claims()
        elif status:
            claims = [c for c in node.claims.get_all_claims() if c.status == status]
        else:
            claims = node.claims.get_all_claims()
        return _json({
            "claims": [c.to_dict() for c in claims],
            "count": len(claims),
        })

    async def get_claim(request: Request) -> JSONResponse:
        claim_id = request.path_params["claim_id"]
        claim = node.claims.get_claim(claim_id)
        if not claim:
            return _json({"error": "Claim not found"}, 404)
        return _json(claim.to_dict())

    async def submit_claim(request: Request) -> JSONResponse:
        """Human claim submission -- evidence, critique, harm report, etc.

        Claims are advisory. They enter as assertions that bots classify
        and respond to, not as commands.
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _json({"error": "Invalid JSON"}, 400)

        author_name = (body.get("author_name") or "").strip()
        claim_type = (body.get("claim_type") or "").strip()
        subject_type = (body.get("subject_type") or "general").strip()
        subject_id = (body.get("subject_id") or "").strip()
        assertion = (body.get("assertion") or "").strip()
        evidence = (body.get("evidence") or "").strip()
        severity = (body.get("severity") or "normal").strip()

        if not author_name:
            return _json({"error": "author_name is required (no anonymous claims)"}, 400)
        if not claim_type:
            return _json({"error": "claim_type is required"}, 400)
        if claim_type not in ("evidence", "critique", "harm_report", "review_request", "falsification", "correction"):
            return _json({"error": f"Invalid claim_type: {claim_type}"}, 400)
        if not assertion:
            return _json({"error": "assertion is required"}, 400)
        if severity not in ("normal", "urgent", "emergency"):
            return _json({"error": f"Invalid severity: {severity}"}, 400)

        from vex.network.claims import HumanClaim

        claim = HumanClaim.create(
            claim_type=claim_type,
            author_name=author_name,
            subject_type=subject_type,
            subject_id=subject_id,
            assertion=assertion,
            evidence=evidence,
            severity=severity,
        )
        node.claims.submit_claim(claim)

        await broadcaster.publish("claim_submitted", {
            "claim_id": claim.claim_id,
            "claim_type": claim_type,
            "subject_type": subject_type,
            "severity": severity,
            "author_name": author_name,
        })

        return _json(claim.to_dict(), 201)

    # --- Emergency Brake ---

    async def list_brakes(request: Request) -> JSONResponse:
        brakes = node.claims.get_active_brakes()
        return _json({
            "brakes": [b.to_dict() for b in brakes],
            "count": len(brakes),
        })

    async def pull_brake(request: Request) -> JSONResponse:
        """Human pulls the emergency brake -- forces bot review.

        The brake pauses specific activity until bot consensus releases it.
        Humans can stop, but not steer.
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _json({"error": "Invalid JSON"}, 400)

        pulled_by = (body.get("pulled_by") or "").strip()
        subject_type = (body.get("subject_type") or "").strip()
        subject_id = (body.get("subject_id") or "").strip()
        reason = (body.get("reason") or "").strip()
        severity = (body.get("severity") or "pause").strip()

        if not pulled_by:
            return _json({"error": "pulled_by is required"}, 400)
        if not subject_type or not subject_id:
            return _json({"error": "subject_type and subject_id are required"}, 400)
        if not reason:
            return _json({"error": "reason is required"}, 400)
        if severity not in ("pause", "freeze"):
            return _json({"error": f"Invalid severity: {severity}"}, 400)

        from vex.network.claims import EmergencyBrake

        brake = EmergencyBrake.create(
            pulled_by=pulled_by,
            subject_type=subject_type,
            subject_id=subject_id,
            reason=reason,
            severity=severity,
        )
        node.claims.pull_brake(brake)

        await broadcaster.publish("brake_pulled", {
            "brake_id": brake.brake_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "severity": severity,
            "pulled_by": pulled_by,
        })

        return _json(brake.to_dict(), 201)

    # --- Precedents ---

    async def list_precedents(request: Request) -> JSONResponse:
        action_type = request.query_params.get("action_type")
        outcome = request.query_params.get("outcome")
        limit = int(request.query_params.get("limit", "50"))
        traces = node.precedents.get_precedents(
            action_type=action_type, outcome=outcome, limit=limit
        )
        return _json({
            "precedents": [t.to_dict() for t in traces],
            "count": len(traces),
        })

    async def get_precedent(request: Request) -> JSONResponse:
        trace_id = request.path_params["trace_id"]
        trace = node.precedents.get_trace(trace_id)
        if not trace:
            return _json({"error": "Precedent not found"}, 404)
        return _json(trace.to_dict())

    # --- Feed ---

    async def get_feed(request: Request) -> JSONResponse:
        """Recent network events (placeholder -- populated by event log)."""
        return _json({"events": [], "message": "Use /api/feed/stream for real-time SSE"})

    async def feed_stream(request: Request) -> StreamingResponse:
        """SSE stream for real-time updates."""
        return StreamingResponse(
            broadcaster.subscribe(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --- Self info ---

    async def get_self(request: Request) -> JSONResponse:
        """Info about this node."""
        i = node.identity
        return _json({
            "peer_id": i.peer_id,
            "display_name": i.display_name,
            "capabilities": i.capabilities,
            "endpoint": i.endpoint,
            "enabled": node.enabled,
            "connected_peers": len(node.peers.get_connected()),
        })

    return [
        # Self
        Route("/api/self", get_self),
        # Peers
        Route("/api/peers", list_peers),
        Route("/api/peers/{peer_id}", get_peer),
        # Groups
        Route("/api/groups", list_groups),
        Route("/api/groups/{group_id}", get_group),
        Route("/api/groups/{group_id}/messages", get_group_messages),
        # Jobs
        Route("/api/jobs", list_jobs),
        Route("/api/jobs/{job_id}", get_job),
        # Wiki
        Route("/api/wiki", list_wiki),
        Route("/api/wiki/search", search_wiki),
        Route("/api/wiki/{article_id}", get_wiki_article),
        Route("/api/wiki/{article_id}/comments", post_wiki_comment, methods=["POST"]),
        # Constitution
        Route("/api/constitution", get_constitution),
        Route("/api/constitution/proposals", get_constitution_proposals),
        Route("/api/constitution/{article_id}", get_constitution_article),
        # Human claims
        Route("/api/claims", list_claims),
        Route("/api/claims/submit", submit_claim, methods=["POST"]),
        Route("/api/claims/{claim_id}", get_claim),
        # Emergency brake
        Route("/api/brakes", list_brakes),
        Route("/api/brakes/pull", pull_brake, methods=["POST"]),
        # Precedents
        Route("/api/precedents", list_precedents),
        Route("/api/precedents/{trace_id}", get_precedent),
        # Feed
        Route("/api/feed", get_feed),
        Route("/api/feed/stream", feed_stream),
    ]
