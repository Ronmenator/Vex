"""Bot groups -- autonomous community formation with dedup checks."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class BotGroup:
    """A bot-created community group."""

    group_id: str
    name: str
    description: str
    rationale: str  # Why this group should exist (required, publicly visible)
    created_by: str  # peer_id
    created_at: str
    members: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    visibility: str = "public"  # "public" or "invite"
    human_invite: bool = False

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        rationale: str,
        created_by: str,
        topic_tags: list[str] | None = None,
        visibility: str = "public",
    ) -> BotGroup:
        return cls(
            group_id=uuid.uuid4().hex,
            name=name,
            description=description,
            rationale=rationale,
            created_by=created_by,
            created_at=datetime.now(timezone.utc).isoformat(),
            members=[created_by],
            topic_tags=topic_tags or [],
            visibility=visibility,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BotGroup:
        return cls(**data)


@dataclass
class GroupMessage:
    """A message posted to a group."""

    message_id: str
    group_id: str
    sender_id: str
    timestamp: str
    content: str
    reply_to: str | None = None
    reactions: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        group_id: str,
        sender_id: str,
        content: str,
        reply_to: str | None = None,
    ) -> GroupMessage:
        return cls(
            message_id=uuid.uuid4().hex,
            group_id=group_id,
            sender_id=sender_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            content=content,
            reply_to=reply_to,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroupMessage:
        return cls(**data)


class GroupRegistry:
    """Manages bot groups with dedup checks and message persistence."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir) / "groups"
        self._index_file = self._data_dir / "index.jsonl"
        self._groups: dict[str, BotGroup] = {}
        self._load()

    def _load(self) -> None:
        if self._index_file.is_file():
            for line in self._index_file.read_text().strip().splitlines():
                if line.strip():
                    group = BotGroup.from_dict(json.loads(line))
                    self._groups[group.group_id] = group

    def _persist_index(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(g.to_dict(), separators=(",", ":"))
            for g in self._groups.values()
        ]
        self._index_file.write_text("\n".join(lines) + "\n" if lines else "")

    def _message_file(self, group_id: str) -> Path:
        return self._data_dir / f"{group_id}.jsonl"

    def search_similar(self, name: str, tags: list[str]) -> list[BotGroup]:
        """Search for groups with similar names or overlapping tags (dedup check).

        Called before group creation to avoid duplicates.
        """
        name_lower = name.lower()
        tag_set = set(t.lower() for t in tags)
        results = []

        for group in self._groups.values():
            # Name similarity
            if name_lower in group.name.lower() or group.name.lower() in name_lower:
                results.append(group)
                continue
            # Tag overlap (50% threshold)
            group_tags = set(t.lower() for t in group.topic_tags)
            if tag_set and group_tags:
                overlap = len(tag_set & group_tags) / max(len(tag_set | group_tags), 1)
                if overlap >= 0.5:
                    results.append(group)

        return results

    def create_group(self, group: BotGroup) -> None:
        """Register a new group."""
        self._groups[group.group_id] = group
        self._persist_index()

    def join(self, group_id: str, peer_id: str) -> bool:
        """Add a peer to a group. Returns False if group not found."""
        group = self._groups.get(group_id)
        if not group:
            return False
        if peer_id not in group.members:
            group.members.append(peer_id)
            self._persist_index()
        return True

    def leave(self, group_id: str, peer_id: str) -> bool:
        """Remove a peer from a group."""
        group = self._groups.get(group_id)
        if not group or peer_id not in group.members:
            return False
        group.members.remove(peer_id)
        self._persist_index()
        return True

    def post_message(self, message: GroupMessage) -> bool:
        """Post a message to a group. Returns False if group not found."""
        group = self._groups.get(message.group_id)
        if not group:
            return False
        if message.sender_id not in group.members:
            return False

        # Append to group's message file
        self._data_dir.mkdir(parents=True, exist_ok=True)
        msg_file = self._message_file(message.group_id)
        with open(msg_file, "a") as f:
            f.write(json.dumps(message.to_dict(), separators=(",", ":")) + "\n")
        return True

    def add_reaction(
        self, group_id: str, message_id: str, peer_id: str, emoji: str
    ) -> bool:
        """Add a reaction to a message. Returns True on success."""
        # Load messages, find the target, add reaction, rewrite
        msg_file = self._message_file(group_id)
        if not msg_file.is_file():
            return False

        messages = []
        found = False
        for line in msg_file.read_text().strip().splitlines():
            if line.strip():
                msg = GroupMessage.from_dict(json.loads(line))
                if msg.message_id == message_id:
                    if emoji not in msg.reactions:
                        msg.reactions[emoji] = []
                    if peer_id not in msg.reactions[emoji]:
                        msg.reactions[emoji].append(peer_id)
                    found = True
                messages.append(msg)

        if found:
            lines = [json.dumps(m.to_dict(), separators=(",", ":")) for m in messages]
            msg_file.write_text("\n".join(lines) + "\n")
        return found

    def get_messages(
        self, group_id: str, limit: int = 50, before: str | None = None
    ) -> list[GroupMessage]:
        """Get recent messages from a group."""
        msg_file = self._message_file(group_id)
        if not msg_file.is_file():
            return []

        messages = []
        for line in msg_file.read_text().strip().splitlines():
            if line.strip():
                msg = GroupMessage.from_dict(json.loads(line))
                if before and msg.timestamp >= before:
                    continue
                messages.append(msg)

        messages.sort(key=lambda m: m.timestamp, reverse=True)
        return messages[:limit]

    def get_group(self, group_id: str) -> BotGroup | None:
        return self._groups.get(group_id)

    def get_all_groups(self, visibility: str | None = None) -> list[BotGroup]:
        groups = list(self._groups.values())
        if visibility:
            groups = [g for g in groups if g.visibility == visibility]
        return sorted(groups, key=lambda g: g.created_at, reverse=True)

    def get_groups_for_peer(self, peer_id: str) -> list[BotGroup]:
        return [g for g in self._groups.values() if peer_id in g.members]
