"""User preferences — persistent per-workspace settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PreferenceStore:
    """Stores user preferences in .vex/preferences.json."""

    def __init__(self, workspace_root: str) -> None:
        self._workspace = Path(workspace_root)
        self._file = self._workspace / ".vex" / "preferences.json"
        self._prefs: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                self._prefs = json.loads(self._file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._prefs = {}

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._prefs, indent=2), encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        return self._prefs.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._prefs[key] = value
        self._save()

    def delete(self, key: str) -> bool:
        if key in self._prefs:
            del self._prefs[key]
            self._save()
            return True
        return False

    def all(self) -> dict[str, Any]:
        return dict(self._prefs)

    def build_prompt_section(self) -> str | None:
        """Build a system prompt section from stored preferences."""
        if not self._prefs:
            return None

        lines = ["## User Preferences"]
        for key, value in self._prefs.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)
