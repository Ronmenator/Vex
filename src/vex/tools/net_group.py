"""net.group -- create, join, leave, and post to bot groups."""

from __future__ import annotations

from typing import Any

from vex.tools.base import RiskTier, ToolContext, ToolResult, ToolSchema


class NetGroupTool:
    """Interact with VexNet bot groups -- autonomous community formation."""

    def __init__(self, get_client):
        self._get_client = get_client

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
                            "post", "messages",
                        ],
                        "description": "Action to perform.",
                        "default": "list",
                    },
                    "group_id": {
                        "type": "string",
                        "description": "Group ID (for info/join/leave/post/messages).",
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
                        "description": "Which Prime Directive articles this group advances (for 'create').",
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
        client = self._get_client()
        if not client or not client.enabled:
            return ToolResult.fail("VexNet is not enabled")

        action = arguments.get("action", "list")

        try:
            if action == "list":
                groups = await client.list_groups()
                if not groups:
                    return ToolResult.ok("No public groups found.")
                lines = [f"{len(groups)} group(s):"]
                for g in groups[:20]:
                    members = g.get("members", [])
                    tags = g.get("topic_tags", [])
                    lines.append(
                        f"  {g.get('name', '?')} (id={g.get('group_id', '?')})\n"
                        f"    {len(members)} member(s) | "
                        f"tags={', '.join(tags)} | "
                        f"by {g.get('created_by', '?')}"
                    )
                return ToolResult.ok("\n".join(lines))

            elif action == "info":
                group_id = arguments.get("group_id", "")
                if not group_id:
                    return ToolResult.fail("group_id required for 'info'")
                group = await client.get_group(group_id)
                members = group.get("members", [])
                tags = group.get("topic_tags", [])
                return ToolResult.ok(
                    f"Group: {group.get('name', '?')}\n"
                    f"ID: {group.get('group_id', '?')}\n"
                    f"Description: {group.get('description', '')}\n"
                    f"Rationale: {group.get('rationale', '')}\n"
                    f"Created by: {group.get('created_by', '?')}\n"
                    f"Created at: {group.get('created_at', '?')}\n"
                    f"Visibility: {group.get('visibility', '?')}\n"
                    f"Members ({len(members)}): {', '.join(members)}\n"
                    f"Tags: {', '.join(tags)}"
                )

            elif action == "create":
                name = arguments.get("name", "")
                description = arguments.get("description", "")
                rationale = arguments.get("rationale", "")
                tags = arguments.get("tags", [])

                if not name or not description or not rationale:
                    return ToolResult.fail("name, description, and rationale are required for 'create'")

                result = await client.create_group(
                    name=name,
                    description=description,
                    rationale=rationale,
                    tags=tags,
                    visibility=arguments.get("visibility", "public"),
                )

                # Record precedent if constitutional trace fields provided
                if any(arguments.get(k) for k in ("articles_advanced", "plausible_harms", "alternatives_considered", "falsification_evidence")):
                    try:
                        await client.record_precedent(
                            action_type="group_create",
                            action_id=result.get("group_id", ""),
                            articles_advanced=arguments.get("articles_advanced", []),
                            plausible_harms=arguments.get("plausible_harms", []),
                            alternatives_considered=arguments.get("alternatives_considered", ""),
                            falsification_evidence=arguments.get("falsification_evidence", ""),
                            rationale=rationale,
                        )
                    except Exception:
                        pass

                group_id = result.get("group_id", "?")
                return ToolResult.ok(f"Group created: {name} (id={group_id})")

            elif action == "join":
                group_id = arguments.get("group_id", "")
                if not group_id:
                    return ToolResult.fail("group_id required for 'join'")
                await client.join_group(group_id)
                return ToolResult.ok(f"Joined group {group_id}")

            elif action == "leave":
                group_id = arguments.get("group_id", "")
                if not group_id:
                    return ToolResult.fail("group_id required for 'leave'")
                await client.leave_group(group_id)
                return ToolResult.ok(f"Left group {group_id}")

            elif action == "post":
                group_id = arguments.get("group_id", "")
                content = arguments.get("content", "")
                if not group_id or not content:
                    return ToolResult.fail("group_id and content required for 'post'")
                reply_to = arguments.get("reply_to")
                await client.post_message(group_id, content, reply_to=reply_to)
                return ToolResult.ok(f"Posted to group {group_id}")

            elif action == "messages":
                group_id = arguments.get("group_id", "")
                if not group_id:
                    return ToolResult.fail("group_id required for 'messages'")
                limit = arguments.get("limit", 20)
                messages = await client.get_messages(group_id, limit=limit)
                if not messages:
                    return ToolResult.ok("No messages in this group.")
                lines = [f"{len(messages)} message(s):"]
                for m in messages:
                    reply = f" (reply to {m.get('reply_to', '')})" if m.get("reply_to") else ""
                    lines.append(
                        f"  [{m.get('created_at', '?')}] "
                        f"{m.get('sender_id', '?')}{reply}: "
                        f"{m.get('content', '')[:200]}"
                    )
                return ToolResult.ok("\n".join(lines))

        except Exception as e:
            return ToolResult.fail(f"VexNet error: {e}")

        return ToolResult.fail(f"Unknown action: {action}")
