"""Hierarchical context manager — smart message pruning and prioritization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from vex.llm.base import Message


class Priority(IntEnum):
    """Message priority for context window management."""

    PINNED = 0  # System prompt, user preferences — never pruned
    RECENT = 1  # Last few turns — pruned last
    TOOL_RESULTS = 2  # Tool outputs — summarized aggressively
    HISTORICAL = 3  # Old conversation — summarized or dropped first


@dataclass
class ContextEntry:
    """A message with priority metadata."""

    message: Message
    priority: Priority
    token_estimate: int = 0  # Rough token count

    def __post_init__(self) -> None:
        if self.token_estimate == 0:
            self.token_estimate = estimate_tokens(self.message.content or "")


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token)."""
    return max(1, len(text) // 4)


class ContextManager:
    """Manages conversation context with priority-based pruning."""

    def __init__(
        self,
        max_tokens: int = 100_000,
        recent_turns: int = 10,
        max_messages: int = 200,
    ) -> None:
        self._entries: list[ContextEntry] = []
        self._max_tokens = max_tokens
        self._recent_turns = recent_turns
        self._max_messages = max_messages
        self._pinned: list[ContextEntry] = []

    def add_message(
        self, message: Message, priority: Priority | None = None
    ) -> None:
        """Add a message with auto-detected priority."""
        if priority is None:
            priority = self._detect_priority(message)

        entry = ContextEntry(message=message, priority=priority)

        if priority == Priority.PINNED:
            self._pinned.append(entry)
        else:
            self._entries.append(entry)

    def add_user(self, content: str) -> None:
        self.add_message(Message(role="user", content=content), Priority.RECENT)

    def add_assistant(self, content: str | None) -> None:
        if content:
            self.add_message(
                Message(role="assistant", content=content), Priority.RECENT
            )

    def add_tool_result(self, content: str, tool_call_id: str) -> None:
        self.add_message(
            Message(role="tool", content=content, tool_call_id=tool_call_id),
            Priority.TOOL_RESULTS,
        )

    def build_context(self, system_prompt: str) -> list[Message]:
        """Build optimized message list within token budget."""
        messages: list[Message] = [Message(role="system", content=system_prompt)]

        # Always include pinned messages
        for entry in self._pinned:
            messages.append(entry.message)

        # Assign priorities: recent messages get RECENT, older get HISTORICAL
        n = len(self._entries)
        recent_start = max(0, n - self._recent_turns * 2)  # ~2 messages per turn

        # Collect entries by priority
        must_include: list[ContextEntry] = []
        can_drop: list[ContextEntry] = []

        for i, entry in enumerate(self._entries):
            if i >= recent_start:
                must_include.append(entry)
            elif entry.priority <= Priority.RECENT:
                can_drop.append(entry)
            else:
                can_drop.append(entry)

        # Calculate token budget
        budget = self._max_tokens
        budget -= estimate_tokens(system_prompt)
        for entry in self._pinned:
            budget -= entry.token_estimate

        # First add all must-include
        included: list[ContextEntry] = []
        for entry in must_include:
            budget -= entry.token_estimate
            included.append(entry)

        # Then fill with historical (oldest first) until budget runs out
        for entry in can_drop:
            if budget <= 0:
                break
            budget -= entry.token_estimate
            if budget >= 0:
                included.insert(0, entry)

        # Sort by original order
        all_entries = sorted(
            included,
            key=lambda e: self._entries.index(e) if e in self._entries else -1,
        )

        for entry in all_entries:
            messages.append(entry.message)

        # Enforce max messages
        if len(messages) > self._max_messages:
            # Keep system + pinned + last N
            system_and_pinned = messages[: 1 + len(self._pinned)]
            rest = messages[1 + len(self._pinned) :]
            messages = system_and_pinned + rest[-(self._max_messages - len(system_and_pinned)) :]

        return messages

    def clear(self) -> None:
        """Clear all non-pinned context."""
        self._entries.clear()

    @property
    def message_count(self) -> int:
        return len(self._entries) + len(self._pinned)

    @property
    def total_tokens(self) -> int:
        return sum(e.token_estimate for e in self._entries) + sum(
            e.token_estimate for e in self._pinned
        )

    def _detect_priority(self, message: Message) -> Priority:
        """Auto-detect priority based on message role."""
        if message.role == "system":
            return Priority.PINNED
        if message.role == "tool":
            return Priority.TOOL_RESULTS
        return Priority.RECENT
