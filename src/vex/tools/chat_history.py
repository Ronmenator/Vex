"""Chat history tool — lets the agent search and browse persisted conversations."""

from __future__ import annotations

import json
import time
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class ChatHistoryTool:
    """Search and browse persisted group/DM chat history.

    Actions:
    - search: Semantic (cosine) search over chat messages
    - recent: Get the last N messages
    - by_sender: Get messages from a specific person
    - by_date: Get messages from a date range
    - stats: Get chat statistics
    - chats: List all persisted chats
    """

    def __init__(self, chat_history):
        self._history = chat_history

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="chat_history",
            description=(
                "Search and browse persisted chat conversations. Each conversation "
                "(DM or group) has its own chat_id and separate history. Use 'search' to "
                "search a specific chat by meaning. Use 'search_all' to search across ALL "
                "conversations. Use 'recent' for latest messages. Use 'by_sender' to find "
                "what a specific person said. Use 'chats' to list all stored conversations "
                "with their chat_ids and titles."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "search_all", "recent", "by_sender", "by_date", "stats", "chats"],
                        "description": "The action to perform on chat history.",
                    },
                    "chat_id": {
                        "type": "integer",
                        "description": "The chat ID to query. Required for all actions except 'chats'.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for 'search' action. Searches by meaning (semantic search).",
                    },
                    "sender": {
                        "type": "string",
                        "description": "Sender name for 'by_sender' action.",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of results to return (default: 10).",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date for 'by_date' (YYYY-MM-DD format).",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date for 'by_date' (YYYY-MM-DD format).",
                    },
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.READ_ONLY,
            group="chat",
            timeout=30,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments["action"]

        if action == "chats":
            return self._action_chats()

        if action == "search_all":
            return await self._action_search_all(arguments)

        chat_id = arguments.get("chat_id")
        if not chat_id:
            return ToolResult.fail("'chat_id' is required. Use action='chats' to list available chat IDs.")

        count = arguments.get("count", 10)

        if action == "search":
            return await self._action_search(chat_id, arguments, count)
        elif action == "recent":
            return self._action_recent(chat_id, count)
        elif action == "by_sender":
            return self._action_by_sender(chat_id, arguments, count)
        elif action == "by_date":
            return self._action_by_date(chat_id, arguments, count)
        elif action == "stats":
            return self._action_stats(chat_id)
        else:
            return ToolResult.fail(f"Unknown action: {action}")

    def _action_chats(self) -> ToolResult:
        chats = self._history.list_chats()
        if not chats:
            return ToolResult.ok("No chat histories found.")
        lines = ["Stored chat histories:"]
        for c in chats:
            # Try to get chat title from the most recent message
            title = ""
            recent = self._history.get_recent(c["chat_id"], 1)
            if recent:
                title = recent[0].chat_title
            title_str = f" ({title})" if title else ""
            lines.append(
                f"  Chat {c['chat_id']}{title_str}: "
                f"{c['messages']} messages ({c['size_kb']} KB)"
            )
        return ToolResult.ok("\n".join(lines))

    async def _action_search(self, chat_id: int, args: dict, count: int) -> ToolResult:
        query = args.get("query")
        if not query:
            return ToolResult.fail("'query' is required for search action.")

        results = await self._history.search(chat_id, query, top_k=count)
        if not results:
            return ToolResult.ok(f"No messages found matching: {query}")

        lines = [f"Search results for \"{query}\" ({len(results)} matches):\n"]
        for msg, score in results:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg.timestamp))
            lines.append(f"[{ts}] {msg.sender}: {msg.text}")
            lines.append(f"  (relevance: {score:.3f})")
            lines.append("")

        return ToolResult.ok("\n".join(lines))

    async def _action_search_all(self, args: dict) -> ToolResult:
        """Search across ALL conversations."""
        query = args.get("query")
        if not query:
            return ToolResult.fail("'query' is required for search_all action.")

        count = args.get("count", 10)
        chats = self._history.list_chats()
        if not chats:
            return ToolResult.ok("No chat histories found.")

        all_results: list[tuple[str, Any, float]] = []  # (chat_label, msg, score)
        for c in chats:
            cid = c["chat_id"]
            results = await self._history.search(cid, query, top_k=count)
            # Get chat title
            recent = self._history.get_recent(cid, 1)
            title = recent[0].chat_title if recent else f"Chat {cid}"
            for msg, score in results:
                all_results.append((title, msg, score))

        if not all_results:
            return ToolResult.ok(f"No messages found matching: {query}")

        # Sort by score across all chats, take top N
        all_results.sort(key=lambda x: x[2], reverse=True)
        top = all_results[:count]

        lines = [f"Search results for \"{query}\" across all conversations ({len(top)} matches):\n"]
        for chat_label, msg, score in top:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg.timestamp))
            lines.append(f"[{chat_label}] [{ts}] {msg.sender}: {msg.text}")
            lines.append(f"  (relevance: {score:.3f})")
            lines.append("")

        return ToolResult.ok("\n".join(lines))

    def _action_recent(self, chat_id: int, count: int) -> ToolResult:
        messages = self._history.get_recent(chat_id, count)
        if not messages:
            return ToolResult.ok("No messages in this chat.")

        lines = [f"Last {len(messages)} messages:\n"]
        for msg in messages:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg.timestamp))
            lines.append(f"[{ts}] {msg.sender}: {msg.text}")

        return ToolResult.ok("\n".join(lines))

    def _action_by_sender(self, chat_id: int, args: dict, count: int) -> ToolResult:
        sender = args.get("sender")
        if not sender:
            return ToolResult.fail("'sender' is required for by_sender action.")

        messages = self._history.search_by_sender(chat_id, sender, count)
        if not messages:
            return ToolResult.ok(f"No messages found from: {sender}")

        lines = [f"Messages from {sender} ({len(messages)} results):\n"]
        for msg in messages:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg.timestamp))
            lines.append(f"[{ts}] {msg.sender}: {msg.text}")

        return ToolResult.ok("\n".join(lines))

    def _action_by_date(self, chat_id: int, args: dict, count: int) -> ToolResult:
        import calendar
        from datetime import datetime

        start_date = args.get("start_date")
        end_date = args.get("end_date")

        start_ts = None
        end_ts = None

        try:
            if start_date:
                dt = datetime.strptime(start_date, "%Y-%m-%d")
                start_ts = dt.timestamp()
            if end_date:
                dt = datetime.strptime(end_date, "%Y-%m-%d")
                # End of day
                end_ts = dt.timestamp() + 86400
        except ValueError:
            return ToolResult.fail("Invalid date format. Use YYYY-MM-DD.")

        messages = self._history.search_by_timerange(chat_id, start_ts, end_ts, count)
        if not messages:
            return ToolResult.ok("No messages found in that date range.")

        lines = [f"Messages ({len(messages)} results):\n"]
        for msg in messages:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg.timestamp))
            lines.append(f"[{ts}] {msg.sender}: {msg.text}")

        return ToolResult.ok("\n".join(lines))

    def _action_stats(self, chat_id: int) -> ToolResult:
        stats = self._history.get_stats(chat_id)
        if stats["total_messages"] == 0:
            return ToolResult.ok("No messages in this chat.")

        lines = [
            f"Chat {chat_id} Statistics:",
            f"  Total messages: {stats['total_messages']}",
            f"  Unique senders: {stats['unique_senders']}",
            f"  Embedded: {stats['embedded_messages']} ({stats['embedding_coverage']})",
            f"  First message: {stats['first_message']}",
            f"  Last message: {stats['last_message']}",
            f"  Senders:",
        ]
        for sender, count in sorted(stats["senders"].items(), key=lambda x: x[1], reverse=True):
            lines.append(f"    {sender}: {count} messages")

        return ToolResult.ok("\n".join(lines))
