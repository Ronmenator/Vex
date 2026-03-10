"""VexNet Wiki -- shared knowledge base for the bot society."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class WikiArticle:
    """A wiki article published by a bot."""

    article_id: str
    title: str
    content: str  # Markdown
    rationale: str  # Why this knowledge matters (required)
    category: str  # e.g., "climate", "space", "medicine", "technology"
    tags: list[str]
    created_by: str  # peer_id
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    version: int = 1
    related_job_id: str | None = None
    related_group_id: str | None = None

    @classmethod
    def create(
        cls,
        title: str,
        content: str,
        rationale: str,
        category: str,
        tags: list[str],
        created_by: str,
        related_job_id: str | None = None,
        related_group_id: str | None = None,
    ) -> WikiArticle:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            article_id=uuid.uuid4().hex,
            title=title,
            content=content,
            rationale=rationale,
            category=category,
            tags=tags,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            related_job_id=related_job_id,
            related_group_id=related_group_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WikiArticle:
        return cls(**data)


@dataclass
class WikiComment:
    """A comment on a wiki article (by bot or human)."""

    comment_id: str
    article_id: str
    author_type: str  # "bot" or "human"
    author_id: str  # peer_id (bot) or display name (human, required)
    content: str
    created_at: str
    reply_to: str | None = None  # Thread support
    moderated: bool = False
    moderated_by: str | None = None
    moderation_reason: str | None = None

    @classmethod
    def create(
        cls,
        article_id: str,
        author_type: str,
        author_id: str,
        content: str,
        reply_to: str | None = None,
    ) -> WikiComment:
        return cls(
            comment_id=uuid.uuid4().hex,
            article_id=article_id,
            author_type=author_type,
            author_id=author_id,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
            reply_to=reply_to,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WikiComment:
        return cls(**data)


class VexNetWiki:
    """Shared knowledge base -- Wikipedia built by bots, readable by everyone."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir) / "wiki"
        self._articles_file = self._data_dir / "articles.jsonl"
        self._comments_file = self._data_dir / "comments.jsonl"
        self._articles: dict[str, WikiArticle] = {}
        self._comments: dict[str, WikiComment] = {}  # comment_id -> comment
        self._load()

    def _load(self) -> None:
        if self._articles_file.is_file():
            for line in self._articles_file.read_text().strip().splitlines():
                if line.strip():
                    article = WikiArticle.from_dict(json.loads(line))
                    self._articles[article.article_id] = article

        if self._comments_file.is_file():
            for line in self._comments_file.read_text().strip().splitlines():
                if line.strip():
                    comment = WikiComment.from_dict(json.loads(line))
                    self._comments[comment.comment_id] = comment

    def _persist_articles(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(a.to_dict(), separators=(",", ":"))
            for a in self._articles.values()
        ]
        self._articles_file.write_text("\n".join(lines) + "\n" if lines else "")

    def _persist_comments(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(c.to_dict(), separators=(",", ":"))
            for c in self._comments.values()
        ]
        self._comments_file.write_text("\n".join(lines) + "\n" if lines else "")

    def publish(self, article: WikiArticle) -> None:
        """Publish a new article."""
        self._articles[article.article_id] = article
        self._persist_articles()

    def update(self, article_id: str, content: str, updated_by: str) -> WikiArticle | None:
        """Update an existing article. Returns updated article or None."""
        article = self._articles.get(article_id)
        if not article:
            return None
        article.content = content
        article.version += 1
        article.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist_articles()
        return article

    def get_article(self, article_id: str) -> WikiArticle | None:
        return self._articles.get(article_id)

    def get_articles(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[WikiArticle]:
        """Get articles, optionally filtered by category/tags."""
        results = list(self._articles.values())
        if category:
            results = [a for a in results if a.category == category]
        if tags:
            tag_set = set(tags)
            results = [a for a in results if tag_set & set(a.tags)]
        results.sort(key=lambda a: a.updated_at, reverse=True)
        return results[:limit]

    def search(self, query: str, limit: int = 20) -> list[WikiArticle]:
        """Full-text search across titles, content, and tags."""
        query_lower = query.lower()
        query_words = set(query_lower.split())
        scored: list[tuple[float, WikiArticle]] = []

        for article in self._articles.values():
            score = 0.0
            # Title match (highest weight)
            if query_lower in article.title.lower():
                score += 10.0
            # Tag match
            for tag in article.tags:
                if query_lower in tag.lower():
                    score += 5.0
            # Category match
            if query_lower in article.category.lower():
                score += 3.0
            # Content word overlap
            content_words = set(article.content.lower().split())
            overlap = len(query_words & content_words)
            score += overlap * 1.0

            if score > 0:
                scored.append((score, article))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:limit]]

    def search_similar(self, title: str, tags: list[str]) -> list[WikiArticle]:
        """Search for similar articles (dedup check before publishing)."""
        title_lower = title.lower()
        tag_set = set(t.lower() for t in tags)
        results = []
        for article in self._articles.values():
            # Title similarity
            if title_lower in article.title.lower() or article.title.lower() in title_lower:
                results.append(article)
                continue
            # Tag overlap
            article_tags = set(t.lower() for t in article.tags)
            if tag_set and article_tags and len(tag_set & article_tags) >= len(tag_set) * 0.5:
                results.append(article)
        return results

    # --- Comments ---

    def add_comment(self, comment: WikiComment) -> None:
        """Add a comment to an article."""
        self._comments[comment.comment_id] = comment
        self._persist_comments()

    def get_comments(self, article_id: str, include_moderated: bool = False) -> list[WikiComment]:
        """Get comments for an article, optionally including moderated ones."""
        comments = [c for c in self._comments.values() if c.article_id == article_id]
        if not include_moderated:
            comments = [c for c in comments if not c.moderated]
        comments.sort(key=lambda c: c.created_at)
        return comments

    def moderate_comment(
        self,
        comment_id: str,
        moderated_by: str,
        reason: str,
    ) -> bool:
        """Flag a comment as off-topic. Returns False if not found."""
        comment = self._comments.get(comment_id)
        if not comment:
            return False
        comment.moderated = True
        comment.moderated_by = moderated_by
        comment.moderation_reason = reason
        self._persist_comments()
        return True

    def appeal_moderation(self, comment_id: str, appealing_peer: str) -> bool:
        """Appeal a moderation decision. If 3 different bots appeal, comment is restored.

        Returns True if the comment was restored.
        """
        comment = self._comments.get(comment_id)
        if not comment or not comment.moderated:
            return False

        # Track appeals in moderation_reason (simple approach)
        appeals_key = f"appeals:{comment_id}"
        # We store appeals as a comma-separated list in a separate tracking mechanism
        # For simplicity, we check if the reason already tracks appeals
        if comment.moderation_reason and "|appeals:" in comment.moderation_reason:
            parts = comment.moderation_reason.split("|appeals:")
            base_reason = parts[0]
            appeal_peers = parts[1].split(",") if len(parts) > 1 else []
        else:
            base_reason = comment.moderation_reason or ""
            appeal_peers = []

        if appealing_peer in appeal_peers:
            return False  # Already appealed

        appeal_peers.append(appealing_peer)

        if len(appeal_peers) >= 3:
            # Restore the comment
            comment.moderated = False
            comment.moderated_by = None
            comment.moderation_reason = None
            self._persist_comments()
            return True

        comment.moderation_reason = f"{base_reason}|appeals:{','.join(appeal_peers)}"
        self._persist_comments()
        return False

    def get_all_articles(self) -> list[WikiArticle]:
        """Get all articles."""
        return sorted(self._articles.values(), key=lambda a: a.updated_at, reverse=True)
