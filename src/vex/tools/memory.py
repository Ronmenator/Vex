"""Tool: persistent key-value memory with search."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class MemoryStore:
    """Simple persistent key-value memory backed by a JSONL file."""

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "memory.jsonl"
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load all entries from the JSONL file."""
        if not self._file.exists():
            return
        for line in self._file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entry = json.loads(line)
                    self._entries[entry["key"]] = entry
                except (json.JSONDecodeError, KeyError):
                    continue

    def _save(self) -> None:
        """Write all entries to the JSONL file."""
        lines = [json.dumps(e) for e in self._entries.values()]
        self._file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def set(self, key: str, value: str, tags: list[str] | None = None) -> None:
        self._entries[key] = {
            "key": key,
            "value": value,
            "tags": tags or [],
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        return entry["value"] if entry else None

    def delete(self, key: str) -> bool:
        if key in self._entries:
            del self._entries[key]
            self._save()
            return True
        return False

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search entries by key, value, or tag content."""
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            score = 0
            if query_lower in entry["key"].lower():
                score += 3
            if query_lower in entry["value"].lower():
                score += 1
            for tag in entry.get("tags", []):
                if query_lower in tag.lower():
                    score += 2
            if score > 0:
                results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in results[:limit]]

    def list_keys(self) -> list[str]:
        return list(self._entries.keys())


class MemoryTool:
    """Read and write persistent memory entries."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="memory",
            description=(
                "Read, write, search, and delete persistent memory entries. "
                "Use this to remember information across conversations. "
                "Actions: get, set, delete, search, list."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set", "delete", "search", "list"],
                        "description": "Action to perform",
                    },
                    "key": {
                        "type": "string",
                        "description": "Memory key (for get, set, delete)",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to store (for set)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization (for set)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (for search)",
                    },
                },
                "required": ["action"],
            },
            risk_tier=RiskTier.WRITE_LOCAL,
            group="memory",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments["action"]

        if action == "set":
            key = arguments.get("key")
            value = arguments.get("value")
            if not key or not value:
                return ToolResult.fail("'set' requires 'key' and 'value'.")
            tags = arguments.get("tags", [])
            self._store.set(key, value, tags)
            return ToolResult.ok(f"Stored memory: {key}")

        if action == "get":
            key = arguments.get("key")
            if not key:
                return ToolResult.fail("'get' requires 'key'.")
            value = self._store.get(key)
            if value is None:
                return ToolResult.ok(f"No memory found for key: {key}")
            return ToolResult.ok(value)

        if action == "delete":
            key = arguments.get("key")
            if not key:
                return ToolResult.fail("'delete' requires 'key'.")
            if self._store.delete(key):
                return ToolResult.ok(f"Deleted memory: {key}")
            return ToolResult.ok(f"No memory found for key: {key}")

        if action == "search":
            query = arguments.get("query", "")
            if not query:
                return ToolResult.fail("'search' requires 'query'.")
            results = self._store.search(query)
            if not results:
                return ToolResult.ok("No matching memories found.")
            lines = []
            for r in results:
                tags = ", ".join(r.get("tags", []))
                lines.append(f"[{r['key']}] {r['value'][:200]}" + (f" ({tags})" if tags else ""))
            return ToolResult.ok("\n".join(lines))

        if action == "list":
            keys = self._store.list_keys()
            if not keys:
                return ToolResult.ok("No memories stored.")
            return ToolResult.ok("\n".join(keys))

        return ToolResult.fail(f"Unknown action: {action}")
