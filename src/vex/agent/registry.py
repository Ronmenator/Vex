"""Runtime agent registry — stores agent definitions for sub-agent creation."""

from __future__ import annotations

from .definition import AgentDefinition


class AgentRegistry:
    """Registry of agent definitions, supporting dynamic creation at runtime."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    def register(self, definition: AgentDefinition) -> None:
        """Register an agent definition."""
        self._agents[definition.agent_id] = definition

    def get(self, agent_id: str) -> AgentDefinition | None:
        """Get an agent definition by ID."""
        return self._agents.get(agent_id)

    def list_all(self) -> list[AgentDefinition]:
        """List all registered agent definitions."""
        return list(self._agents.values())

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent definition. Returns True if it existed."""
        if agent_id == "default":
            return False  # Cannot remove default agent
        return self._agents.pop(agent_id, None) is not None
