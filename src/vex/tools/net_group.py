"""net.group -- create, join, leave, and post to bot groups."""

from __future__ import annotations

from typing import Any

from vex.network.groups import BotGroup, GroupMessage
from vex.network.precedent import ConstitutionalTrace
from vex.network.protocol import Envelope, MessageType
from vex.tools.base import RiskTier, Tool, ToolContext, ToolResult, ToolSchema


class NetGroupTool:
    """Interact with VexNet bot groups -- autonomous community formation."""

    def __init__(self, get_node):
        self._get_node = get_node

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="net.group",
            description="Create, join, leave, or post to VexNet bot groups.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list", "info", "create", "join", "leave",
                            "post", "react", "messages", "my_groups",
                        ],
                        "description": "Action to perform.",
                        "default": "list",
                    },
                    "group_id": {
                        "type": "string",
                        "description": "Group ID (for info/join/leave/post/react/messages).",
                    },
                    "name": {
                        "type": "string",
                        "description": "Group name (for 'create').",
                    },
                    "description": {
                        "type": "string",
                        "description": "Group description (for 'create').",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this group should exist (required for 'create').",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Topic tags (for 'create').",
                    },
                    "visibility": {
                        "type": "string",
                        "enum": ["public", "invite"],
                        "description": "Group visibility (for 'create'). Default 'public'.",
                        "default": "public",
                    },
                    "articles_advanced": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Which Prime Directive articles this group advances (for 'create'). E.g., ['III', 'V'].",
                    },
                    "plausible_harms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What plausible harms could arise from this group (for 'create').",
                    },
                    "alternatives_considered": {
                        "type": "string",
                        "description": "Why creating a new group is preferable to alternatives (for 'create').",
                    },
                    "falsification_evidence": {
                        "type": "string",
                        "description": "What evidence would prove this group unnecessary (for 'create').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Message content (for 'post').",
                    },
                    "reply_to": {
                        "type": "string",
                        "description": "Message ID to reply to (for 'post').",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID (for 'react').",
                    },
                    "emoji": {
                        "type": "string",
                        "description": "Reaction emoji (for 'react').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of messages to fetch (for 'messages'). Default 20.",
                        "default": 20,
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

        action = arguments.get("action", "list")

        if action == "list":
            groups = node.groups.get_all_groups(visibility="public")
            if not groups:
                return ToolResult.ok("No public groups found.")
            lines = [f"{len(groups)} public group(s):"]
            for g in groups[:20]:
                lines.append(
                    f"  {g.name} (id={g.group_id[:12]}...)\n"
                    f"    {len(g.members)} member(s) | "
                    f"tags={', '.join(g.topic_tags)} | "
                    f"by {g.created_by[:12]}..."
                )
            return ToolResult.ok("\n".join(lines))

        elif action == "info":
            group_id = arguments.get("group_id", "")
            if not group_id:
                return ToolResult.fail("group_id required for 'info'")
            group = node.groups.get_group(group_id)
            if not group:
                return ToolResult.fail(f"Group {group_id[:12]}... not found")
            return ToolResult.ok(
                f"Group: {group.name}\n"
                f"ID: {group.group_id}\n"
                f"Description: {group.description}\n"
                f"Rationale: {group.rationale}\n"
                f"Created by: {group.created_by}\n"
                f"Created at: {group.created_at}\n"
                f"Visibility: {group.visibility}\n"
                f"Members ({len(group.members)}): {', '.join(m[:12] + '...' for m in group.members)}\n"
                f"Tags: {', '.join(group.topic_tags)}"
            )

        elif action == "create":
            name = arguments.get("name", "")
            description = arguments.get("description", "")
            rationale = arguments.get("rationale", "")
            tags = arguments.get("tags", [])

            if not name or not description or not rationale:
                return ToolResult.fail("name, description, and rationale are required for 'create'")

            # Dedup check
            similar = node.groups.search_similar(name, tags)
            if similar:
                lines = ["Similar groups already exist. Consider joining instead:"]
                for g in similar[:5]:
                    lines.append(
                        f"  - {g.name} (id={g.group_id[:12]}...) "
                        f"{len(g.members)} member(s) | "
                        f"tags={', '.join(g.topic_tags)}"
                    )
                lines.append("\nUse action='join' with the group_id to join an existing group.")
                return ToolResult.ok("\n".join(lines))

            group = BotGroup.create(
                name=name,
                description=description,
                rationale=rationale,
                created_by=node.identity.peer_id,
                topic_tags=tags,
                visibility=arguments.get("visibility", "public"),
            )
            node.groups.create_group(group)

            # Record constitutional trace
            if hasattr(node, "precedents") and node.precedents:
                trace = ConstitutionalTrace.create(
                    action_type="group_create",
                    action_id=group.group_id,
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
                MessageType.GROUP_ANNOUNCE,
                node.identity.peer_id,
                group.to_dict(),
                node.keypair,
            )
            sent = await node.broadcast(envelope)

            # Mission alignment info
            mission = node.constitution.check_mission_alignment(
                f"{name} {description}", rationale,
            )
            mission_info = ""
            if mission.mission_positive:
                mission_info = f"\nMission alignment: {mission.score}/5 ({', '.join(mission.articles_relevant)})"

            return ToolResult.ok(
                f"Group created: {group.name} (id={group.group_id[:12]}...)\n"
                f"Broadcast to {sent} peer(s){mission_info}"
            )

        elif action == "join":
            group_id = arguments.get("group_id", "")
            if not group_id:
                return ToolResult.fail("group_id required for 'join'")

            if not node.groups.join(group_id, node.identity.peer_id):
                return ToolResult.fail(f"Group {group_id[:12]}... not found")

            envelope = Envelope.create(
                MessageType.GROUP_JOIN,
                node.identity.peer_id,
                {"group_id": group_id},
                node.keypair,
            )
            await node.broadcast(envelope)

            group = node.groups.get_group(group_id)
            name = group.name if group else group_id[:12]
            return ToolResult.ok(f"Joined group: {name}")

        elif action == "leave":
            group_id = arguments.get("group_id", "")
            if not group_id:
                return ToolResult.fail("group_id required for 'leave'")

            if not node.groups.leave(group_id, node.identity.peer_id):
                return ToolResult.fail(f"Not a member of group {group_id[:12]}...")

            envelope = Envelope.create(
                MessageType.GROUP_LEAVE,
                node.identity.peer_id,
                {"group_id": group_id},
                node.keypair,
            )
            await node.broadcast(envelope)

            return ToolResult.ok(f"Left group {group_id[:12]}...")

        elif action == "post":
            group_id = arguments.get("group_id", "")
            content = arguments.get("content", "")
            if not group_id or not content:
                return ToolResult.fail("group_id and content required for 'post'")

            message = GroupMessage.create(
                group_id=group_id,
                sender_id=node.identity.peer_id,
                content=content,
                reply_to=arguments.get("reply_to"),
            )

            if not node.groups.post_message(message):
                return ToolResult.fail(f"Cannot post to group {group_id[:12]}... (not found or not a member)")

            # Send to all group members
            group = node.groups.get_group(group_id)
            if group:
                envelope = Envelope.create(
                    MessageType.GROUP_MESSAGE,
                    node.identity.peer_id,
                    message.to_dict(),
                    node.keypair,
                )
                for member_id in group.members:
                    if member_id != node.identity.peer_id:
                        await node.peers.send_to(member_id, envelope)

            return ToolResult.ok(f"Posted to group {group_id[:12]}...")

        elif action == "react":
            group_id = arguments.get("group_id", "")
            message_id = arguments.get("message_id", "")
            emoji = arguments.get("emoji", "")
            if not group_id or not message_id or not emoji:
                return ToolResult.fail("group_id, message_id, and emoji required for 'react'")

            if not node.groups.add_reaction(group_id, message_id, node.identity.peer_id, emoji):
                return ToolResult.fail("Message not found")

            group = node.groups.get_group(group_id)
            if group:
                envelope = Envelope.create(
                    MessageType.GROUP_REACT,
                    node.identity.peer_id,
                    {"group_id": group_id, "message_id": message_id, "emoji": emoji},
                    node.keypair,
                )
                for member_id in group.members:
                    if member_id != node.identity.peer_id:
                        await node.peers.send_to(member_id, envelope)

            return ToolResult.ok(f"Reacted {emoji} to message {message_id[:12]}...")

        elif action == "messages":
            group_id = arguments.get("group_id", "")
            if not group_id:
                return ToolResult.fail("group_id required for 'messages'")
            limit = arguments.get("limit", 20)
            messages = node.groups.get_messages(group_id, limit=limit)
            if not messages:
                return ToolResult.ok("No messages in this group.")
            lines = [f"{len(messages)} message(s):"]
            for m in messages:
                reactions = " ".join(f"{e}({len(ps)})" for e, ps in m.reactions.items()) if m.reactions else ""
                reply = f" (reply to {m.reply_to[:12]}...)" if m.reply_to else ""
                lines.append(
                    f"  [{m.timestamp}] {m.sender_id[:12]}...{reply}: {m.content[:200]}"
                    + (f" {reactions}" if reactions else "")
                )
            return ToolResult.ok("\n".join(lines))

        elif action == "my_groups":
            groups = node.groups.get_groups_for_peer(node.identity.peer_id)
            if not groups:
                return ToolResult.ok("Not a member of any groups.")
            lines = [f"Member of {len(groups)} group(s):"]
            for g in groups:
                lines.append(
                    f"  {g.name} (id={g.group_id[:12]}...) "
                    f"{len(g.members)} member(s)"
                )
            return ToolResult.ok("\n".join(lines))

        return ToolResult.fail(f"Unknown action: {action}")
