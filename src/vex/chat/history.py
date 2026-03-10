"""Persistent chat history with vector (cosine) search.

Messages are stored as JSONL per chat. Embeddings are generated via the
configured LLM provider's embedding endpoint and stored alongside messages
for semantic search.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """A single persisted chat message."""
    sender: str
    text: str
    timestamp: float
    chat_id: int
    chat_title: str = ""
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Don't serialize None embeddings
        if d["embedding"] is None:
            del d["embedding"]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChatMessage:
        return cls(
            sender=d["sender"],
            text=d["text"],
            timestamp=d["timestamp"],
            chat_id=d["chat_id"],
            chat_title=d.get("chat_title", ""),
            embedding=d.get("embedding"),
        )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors (pure Python)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingClient:
    """Generate embeddings via Ollama's OpenAI-compatible API."""

    def __init__(self, base_url: str = "http://localhost:11434/v1", model: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model or "nomic-embed-text"
        self._available: bool | None = None

    async def is_available(self) -> bool:
        """Check if the embedding endpoint is reachable."""
        if self._available is not None:
            return self._available
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/models")
                self._available = resp.status_code == 200
        except Exception:
            self._available = False
        return self._available

    async def embed(self, text: str) -> list[float] | None:
        """Generate embedding for a single text string."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    json={"input": text, "model": self.model},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["data"][0]["embedding"]
        except Exception as e:
            logger.debug("Embedding failed: %s", e)
            return None

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for multiple texts."""
        # Ollama processes one at a time, but we batch the calls
        results = []
        for text in texts:
            results.append(await self.embed(text))
        return results


class ChatHistory:
    """Persistent, vector-searchable chat history.

    Each chat gets its own JSONL file under the storage directory.
    Embeddings are generated on write and stored inline.
    """

    def __init__(self, storage_dir: str, embedding_client: EmbeddingClient | None = None):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_client = embedding_client

        # In-memory cache: chat_id -> list of messages
        self._cache: dict[int, list[ChatMessage]] = {}
        # Track which chats are loaded
        self._loaded: set[int] = set()

    def _file_path(self, chat_id: int) -> Path:
        return self.storage_dir / f"chat_{chat_id}.jsonl"

    def _load_chat(self, chat_id: int) -> list[ChatMessage]:
        """Load a chat's history from disk into cache."""
        if chat_id in self._loaded:
            return self._cache.get(chat_id, [])

        messages: list[ChatMessage] = []
        filepath = self._file_path(chat_id)
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            messages.append(ChatMessage.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning("Skipping corrupt message: %s", e)

        self._cache[chat_id] = messages
        self._loaded.add(chat_id)
        logger.info("Loaded %d messages for chat %d", len(messages), chat_id)
        return messages

    async def add_message(
        self,
        chat_id: int,
        sender: str,
        text: str,
        chat_title: str = "",
        generate_embedding: bool = True,
    ) -> ChatMessage:
        """Add a message to the history. Persists immediately."""
        msg = ChatMessage(
            sender=sender,
            text=text,
            timestamp=time.time(),
            chat_id=chat_id,
            chat_title=chat_title,
        )

        # Generate embedding if client available
        if generate_embedding and self.embedding_client:
            msg.embedding = await self.embedding_client.embed(text)

        # Append to cache
        messages = self._load_chat(chat_id)
        messages.append(msg)

        # Persist to disk (append)
        filepath = self._file_path(chat_id)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")

        return msg

    async def search(
        self,
        chat_id: int,
        query: str,
        top_k: int = 10,
    ) -> list[tuple[ChatMessage, float]]:
        """Semantic search over a chat's history using cosine similarity.

        Returns list of (message, score) tuples sorted by relevance.
        Falls back to keyword search if embeddings are unavailable.
        """
        messages = self._load_chat(chat_id)
        if not messages:
            return []

        # Try vector search first
        if self.embedding_client:
            query_embedding = await self.embedding_client.embed(query)
            if query_embedding:
                scored = []
                for msg in messages:
                    if msg.embedding:
                        score = _cosine_similarity(query_embedding, msg.embedding)
                        scored.append((msg, score))

                if scored:
                    scored.sort(key=lambda x: x[1], reverse=True)
                    return scored[:top_k]

        # Fallback: keyword search
        return self._keyword_search(messages, query, top_k)

    def _keyword_search(
        self,
        messages: list[ChatMessage],
        query: str,
        top_k: int,
    ) -> list[tuple[ChatMessage, float]]:
        """Simple keyword-based search as fallback."""
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for msg in messages:
            text_lower = msg.text.lower()
            # Score: exact phrase match (high) + word overlap (lower)
            score = 0.0
            if query_lower in text_lower:
                score += 1.0
            word_matches = sum(1 for w in query_words if w in text_lower)
            score += word_matches / max(len(query_words), 1) * 0.5
            if score > 0:
                scored.append((msg, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def get_recent(
        self,
        chat_id: int,
        count: int = 20,
    ) -> list[ChatMessage]:
        """Get the most recent N messages from a chat."""
        messages = self._load_chat(chat_id)
        return messages[-count:]

    def search_by_sender(
        self,
        chat_id: int,
        sender: str,
        count: int = 20,
    ) -> list[ChatMessage]:
        """Get messages from a specific sender."""
        messages = self._load_chat(chat_id)
        sender_lower = sender.lower()
        matching = [m for m in messages if sender_lower in m.sender.lower()]
        return matching[-count:]

    def search_by_timerange(
        self,
        chat_id: int,
        start_ts: float | None = None,
        end_ts: float | None = None,
        count: int = 50,
    ) -> list[ChatMessage]:
        """Get messages within a time range."""
        messages = self._load_chat(chat_id)
        filtered = []
        for m in messages:
            if start_ts and m.timestamp < start_ts:
                continue
            if end_ts and m.timestamp > end_ts:
                continue
            filtered.append(m)
        return filtered[-count:]

    def get_stats(self, chat_id: int) -> dict[str, Any]:
        """Get statistics about a chat's history."""
        messages = self._load_chat(chat_id)
        if not messages:
            return {"total_messages": 0}

        senders: dict[str, int] = {}
        for m in messages:
            senders[m.sender] = senders.get(m.sender, 0) + 1

        embedded = sum(1 for m in messages if m.embedding is not None)

        return {
            "total_messages": len(messages),
            "unique_senders": len(senders),
            "senders": senders,
            "embedded_messages": embedded,
            "embedding_coverage": f"{embedded / len(messages):.0%}" if messages else "0%",
            "first_message": time.strftime("%Y-%m-%d %H:%M", time.localtime(messages[0].timestamp)),
            "last_message": time.strftime("%Y-%m-%d %H:%M", time.localtime(messages[-1].timestamp)),
        }

    def list_chats(self) -> list[dict[str, Any]]:
        """List all persisted chats."""
        chats = []
        for filepath in self.storage_dir.glob("chat_*.jsonl"):
            try:
                chat_id = int(filepath.stem.replace("chat_", ""))
                size = filepath.stat().st_size
                # Quick line count
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = sum(1 for _ in f)
                chats.append({
                    "chat_id": chat_id,
                    "messages": lines,
                    "size_kb": round(size / 1024, 1),
                })
            except (ValueError, OSError):
                continue
        return chats

    async def backfill_embeddings(self, chat_id: int, batch_size: int = 50) -> int:
        """Generate embeddings for messages that don't have them yet."""
        if not self.embedding_client:
            return 0

        messages = self._load_chat(chat_id)
        missing = [m for m in messages if m.embedding is None]
        if not missing:
            return 0

        count = 0
        for i in range(0, len(missing), batch_size):
            batch = missing[i:i + batch_size]
            texts = [m.text for m in batch]
            embeddings = await self.embedding_client.embed_batch(texts)
            for msg, emb in zip(batch, embeddings):
                if emb:
                    msg.embedding = emb
                    count += 1

        # Rewrite the file with updated embeddings
        if count > 0:
            self._rewrite_chat(chat_id)
            logger.info("Backfilled %d embeddings for chat %d", count, chat_id)

        return count

    def _rewrite_chat(self, chat_id: int) -> None:
        """Rewrite a chat's JSONL file from cache (e.g. after embedding backfill)."""
        messages = self._cache.get(chat_id, [])
        filepath = self._file_path(chat_id)
        with open(filepath, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
