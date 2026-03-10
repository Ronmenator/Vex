"""Agent configuration API — CRUD operations for agent definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vex.agent.definition import AgentDefinition
from vex.agent.registry import AgentRegistry


class AgentConfigAPI:
    """Persistent CRUD for agent definitions."""

    def __init__(self, workspace_root: str, registry: AgentRegistry) -> None:
        self._dir = Path(workspace_root) / ".vex" / "agents"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._registry = registry

    def create(
        self,
        agent_id: str,
        display_name: str,
        system_prompt: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        tool_allow: list[str] | None = None,
        tool_deny: list[str] | None = None,
        autonomy_level: int = 1,
    ) -> AgentDefinition:
        """Create and persist an agent definition."""
        agent_def = AgentDefinition(
            agent_id=agent_id,
            display_name=display_name,
            system_prompt=system_prompt,
            llm_provider=llm_provider,
            llm_model=llm_model,
            tool_allow=tool_allow or [],
            tool_deny=tool_deny or [],
            autonomy_level=autonomy_level,
        )
        self._registry.register(agent_def)
        self._save(agent_def)
        return agent_def

    def update(self, agent_id: str, **kwargs: Any) -> AgentDefinition | None:
        """Update fields of an existing agent definition."""
        existing = self._registry.get(agent_id)
        if not existing:
            return None

        fields = {
            "agent_id": existing.agent_id,
            "display_name": existing.display_name,
            "system_prompt": existing.system_prompt,
            "llm_provider": existing.llm_provider,
            "llm_model": existing.llm_model,
            "tool_allow": list(existing.tool_allow),
            "tool_deny": list(existing.tool_deny),
            "max_tool_rounds": existing.max_tool_rounds,
            "autonomy_level": existing.autonomy_level,
            "workspace_root": existing.workspace_root,
            "parent_agent_id": existing.parent_agent_id,
        }
        fields.update(kwargs)
        updated = AgentDefinition(**fields)
        self._registry.register(updated)
        self._save(updated)
        return updated

    def delete(self, agent_id: str) -> bool:
        """Delete an agent definition."""
        if agent_id == "default":
            return False
        self._registry.unregister(agent_id)
        config_file = self._dir / f"{agent_id}.json"
        if config_file.exists():
            config_file.unlink()
            return True
        return False

    def load_persisted(self) -> int:
        """Load all persisted agent definitions. Returns count loaded."""
        count = 0
        for filepath in self._dir.glob("*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                agent_def = AgentDefinition(
                    agent_id=data["agent_id"],
                    display_name=data.get("display_name", data["agent_id"]),
                    system_prompt=data.get("system_prompt"),
                    llm_provider=data.get("llm_provider"),
                    llm_model=data.get("llm_model"),
                    tool_allow=data.get("tool_allow", []),
                    tool_deny=data.get("tool_deny", []),
                    max_tool_rounds=data.get("max_tool_rounds", 25),
                    autonomy_level=data.get("autonomy_level", 1),
                    workspace_root=data.get("workspace_root"),
                    parent_agent_id=data.get("parent_agent_id"),
                )
                self._registry.register(agent_def)
                count += 1
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        return count

    def _save(self, agent_def: AgentDefinition) -> None:
        data = {
            "agent_id": agent_def.agent_id,
            "display_name": agent_def.display_name,
            "system_prompt": agent_def.system_prompt,
            "llm_provider": agent_def.llm_provider,
            "llm_model": agent_def.llm_model,
            "tool_allow": agent_def.tool_allow,
            "tool_deny": agent_def.tool_deny,
            "max_tool_rounds": agent_def.max_tool_rounds,
            "autonomy_level": agent_def.autonomy_level,
            "workspace_root": agent_def.workspace_root,
            "parent_agent_id": agent_def.parent_agent_id,
        }
        filepath = self._dir / f"{agent_def.agent_id}.json"
        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")
