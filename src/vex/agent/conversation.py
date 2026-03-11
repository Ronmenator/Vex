"""Conversation history management."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from vex.llm.base import Message

if TYPE_CHECKING:
    from vex.chat.history import ChatHistory

logger = logging.getLogger(__name__)


class Conversation:
    """Manages the message history for an agent conversation.

    Used by sub-agents and contexts that don't need persistence.
    """

    def __init__(self, max_messages: int = 100) -> None:
        self._messages: list[Message] = []
        self._max_messages = max_messages
        self.user_id: int | None = None
        self.user_name: str | None = None

    def add_user(self, content: str) -> None:
        self._messages.append(Message(role="user", content=content))
        self._trim()

    def add_assistant(self, content: str | None) -> None:
        if content:
            self._messages.append(Message(role="assistant", content=content))
            self._trim()

    async def build_messages(self, system_prompt: str) -> list[Message]:
        """Build the full message list including system prompt and history."""
        return [
            Message(role="system", content=system_prompt),
            *self._messages,
        ]

    def clear(self) -> None:
        self._messages.clear()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def _trim(self) -> None:
        """Keep only the most recent messages."""
        if len(self._messages) > self._max_messages:
            self._messages = self._messages[-self._max_messages :]


class RetrievalConversation(Conversation):
    """Persistent, retrieval-augmented conversation.

    Instead of passing the full message history to the LLM, this class:
    1. Persists every message to ChatHistory (JSONL + embeddings)
    2. On each turn, retrieves relevant past messages via semantic search
    3. Includes only recent short-term + retrieved long-term context

    This allows conversations to span sessions and frontends (CLI <-> Telegram).
    """

    def __init__(
        self,
        chat_id: int,
        chat_history: ChatHistory,
        user_name: str = "",
        chat_title: str = "",
        recent_count: int = 6,
        retrieval_count: int = 10,
    ) -> None:
        # Small buffer — just the current session's recent turns
        super().__init__(max_messages=recent_count * 2)
        self._chat_id = chat_id
        self._chat_history = chat_history
        self._user_name = user_name
        self._chat_title = chat_title
        self._recent_count = recent_count
        self._retrieval_count = retrieval_count
        # Track messages we've already persisted to avoid double-writes
        self._persisted_count = 0

    def add_user(self, content: str) -> None:
        super().add_user(content)
        self._schedule_persist("user", self._user_name or "User", content)

    def add_assistant(self, content: str | None) -> None:
        if content:
            super().add_assistant(content)
            self._schedule_persist("assistant", "Vex", content)

    def _schedule_persist(self, role: str, sender: str, text: str) -> None:
        """Fire-and-forget persistence to ChatHistory."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist(sender, text))
        except RuntimeError:
            # No running loop — skip persistence (shouldn't happen in practice)
            logger.debug("No event loop for persistence, skipping")

    async def _persist(self, sender: str, text: str) -> None:
        """Persist a single message to ChatHistory with embedding."""
        try:
            await self._chat_history.add_message(
                chat_id=self._chat_id,
                sender=sender,
                text=text,
                chat_title=self._chat_title,
            )
        except Exception as e:
            logger.warning("Failed to persist message: %s", e)

    async def build_messages(self, system_prompt: str) -> list[Message]:
        """Build context via retrieval instead of full history.

        Returns:
            [system_prompt, retrieved_context (if any), *recent_messages]
        """
        messages: list[Message] = [
            Message(role="system", content=system_prompt),
        ]

        # Get the latest user message for retrieval query
        last_user_text = None
        for msg in reversed(self._messages):
            if msg.role == "user":
                last_user_text = msg.content
                break

        # Retrieve relevant past context
        if last_user_text:
            context_block = await self._build_retrieval_context(last_user_text)
            if context_block:
                messages.append(
                    Message(role="user", content=context_block)
                )
                messages.append(
                    Message(
                        role="assistant",
                        content="I've reviewed the relevant conversation history above. How can I help you now?",
                    )
                )

        # Append recent in-memory messages (short-term context)
        messages.extend(self._messages)

        return messages

    async def _build_retrieval_context(self, query: str) -> str | None:
        """Retrieve and format relevant past messages."""
        # Semantic search for relevant older messages
        try:
            search_results = await self._chat_history.search(
                self._chat_id, query, top_k=self._retrieval_count
            )
        except Exception as e:
            logger.warning("Retrieval search failed: %s", e)
            search_results = []

        # Recent messages from persistent store (covers cross-frontend context)
        recent_persistent = self._chat_history.get_recent(
            self._chat_id, count=self._recent_count * 2
        )

        # Merge: search results + recent persistent, deduplicated by timestamp
        seen_timestamps: set[float] = set()
        all_messages = []

        # Also exclude messages that are in our current in-memory buffer
        # (they'll be added as regular messages, not context)
        in_memory_texts = {m.content for m in self._messages}

        for msg, score in search_results:
            if msg.timestamp not in seen_timestamps and msg.text not in in_memory_texts:
                seen_timestamps.add(msg.timestamp)
                all_messages.append(msg)

        for msg in recent_persistent:
            if msg.timestamp not in seen_timestamps and msg.text not in in_memory_texts:
                seen_timestamps.add(msg.timestamp)
                all_messages.append(msg)

        if not all_messages:
            return None

        # Sort by timestamp for chronological presentation
        all_messages.sort(key=lambda m: m.timestamp)

        # Format as a context block
        lines = ["## Relevant Conversation History\n"]
        for msg in all_messages:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg.timestamp))
            lines.append(f"[{ts}] {msg.sender}: {msg.text}")

        lines.append(
            "\n(This is retrieved context from past conversations. "
            "The user's current message follows below.)"
        )

        return "\n".join(lines)
