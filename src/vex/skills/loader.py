"""Skill loader — discovers and parses .md skill files.

Skill files live in a directory (default: ``.vex/skills/``) and use YAML
frontmatter to declare metadata.  The markdown body contains the actual
instructions that get injected into the system prompt when the skill is
relevant.

Minimal skill file::

    ---
    name: code-review
    description: Review code for bugs, security issues, and style
    triggers:
      - review
      - code review
      - check my code
    ---

    When asked to review code, follow these steps:
    1. Read the file(s) in question
    2. Look for bugs, security issues, and style problems
    ...
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Regex to split YAML frontmatter from body
_FRONTMATTER_RE = re.compile(
    r"\A\s*---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)


@dataclass
class Skill:
    """A parsed skill definition."""

    name: str
    description: str
    body: str  # The markdown instructions
    triggers: list[str] = field(default_factory=list)
    always: bool = False  # Always inject (no trigger needed)
    tools: list[str] = field(default_factory=list)  # Tools this skill uses
    file_path: str = ""

    @property
    def summary(self) -> str:
        """One-line summary for the skill index in the prompt."""
        return f"- **{self.name}**: {self.description}"


class SkillLoader:
    """Discovers and loads skill files from a directory."""

    def __init__(self, skills_dir: str | Path) -> None:
        self._dir = Path(skills_dir)

    @property
    def directory(self) -> Path:
        return self._dir

    def load_all(self) -> list[Skill]:
        """Load all .md skill files from the skills directory."""
        if not self._dir.is_dir():
            return []

        skills: list[Skill] = []
        for path in sorted(self._dir.glob("*.md")):
            try:
                skill = self._parse_file(path)
                if skill:
                    skills.append(skill)
            except Exception as e:
                logger.warning("Failed to parse skill %s: %s", path.name, e)

        return skills

    def _parse_file(self, path: Path) -> Skill | None:
        """Parse a single skill file into a Skill object."""
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return None

        match = _FRONTMATTER_RE.match(text)
        if not match:
            # No frontmatter — treat entire file as body, derive name from filename
            name = path.stem.replace("_", "-").replace(" ", "-").lower()
            return Skill(
                name=name,
                description=f"Skill: {name}",
                body=text,
                file_path=str(path),
            )

        frontmatter_text = match.group(1)
        body = match.group(2).strip()

        meta = self._parse_yaml_simple(frontmatter_text)

        name = meta.get("name", path.stem.replace("_", "-").lower())
        description = meta.get("description", f"Skill: {name}")

        # Parse triggers (can be a list or comma-separated string)
        triggers_raw = meta.get("triggers", [])
        if isinstance(triggers_raw, str):
            triggers = [t.strip().lower() for t in triggers_raw.split(",") if t.strip()]
        elif isinstance(triggers_raw, list):
            triggers = [str(t).strip().lower() for t in triggers_raw]
        else:
            triggers = []

        # Parse tools
        tools_raw = meta.get("tools", [])
        if isinstance(tools_raw, str):
            tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
        elif isinstance(tools_raw, list):
            tools = [str(t).strip() for t in tools_raw]
        else:
            tools = []

        always = meta.get("always", False)
        if isinstance(always, str):
            always = always.lower() in ("true", "yes", "1")

        return Skill(
            name=name,
            description=description,
            body=body,
            triggers=triggers,
            always=bool(always),
            tools=tools,
            file_path=str(path),
        )

    @staticmethod
    def _parse_yaml_simple(text: str) -> dict[str, Any]:
        """Minimal YAML parser for frontmatter (no dependency on PyYAML).

        Handles:
          - key: value  (scalar)
          - key: true/false  (bool)
          - key:\\n  - item1\\n  - item2  (list)
          - key: item1, item2  (comma-separated → list)
        """
        result: dict[str, Any] = {}
        lines = text.split("\n")
        current_key: str | None = None
        current_list: list[str] | None = None

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # List item under current key
            if stripped.startswith("- ") and current_key is not None:
                if current_list is None:
                    current_list = []
                current_list.append(stripped[2:].strip().strip('"').strip("'"))
                result[current_key] = current_list
                continue

            # Key-value pair
            if ":" in stripped:
                # Flush previous list
                current_list = None

                colon_idx = stripped.index(":")
                key = stripped[:colon_idx].strip().lower()
                value = stripped[colon_idx + 1 :].strip()
                current_key = key

                if not value:
                    # Value will come as list items on subsequent lines
                    result[key] = []
                    current_list = result[key]
                elif value.lower() in ("true", "yes"):
                    result[key] = True
                elif value.lower() in ("false", "no"):
                    result[key] = False
                elif value.startswith('"') and value.endswith('"'):
                    result[key] = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    result[key] = value[1:-1]
                else:
                    result[key] = value

        return result
