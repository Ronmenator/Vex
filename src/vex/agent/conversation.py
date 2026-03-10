"""Conversation history management."""

from __future__ import annotations

from vex.llm.base import Message


class Conversation:
    """Manages the message history for an agent conversation."""

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

    def build_messages(self, system_prompt: str) -> list[Message]:
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
