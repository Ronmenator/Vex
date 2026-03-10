"""Meta-tool: create a new sub-agent at runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vex.agent.definition import AgentDefinition
from vex.agent.registry import AgentRegistry

from .base import RiskTier, ToolContext, ToolResult, ToolSchema


class AgentCreateTool:
    """Create a new sub-agent with a custom system prompt, tools, and LLM config."""

    def __init__(self, registry: AgentRegistry, max_depth: int = 3) -> None:
        self._registry = registry
        self._max_depth = max_depth

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="agent.create",
            description=(
                "Create a new specialist sub-agent with a custom system prompt, tool set, "
                "and LLM configuration. The agent is registered and can be delegated to."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Unique ID for the new agent (lowercase, no spaces)",
                    },
                    "display_name": {
                        "type": "string",
                        "description": "Human-readable name for the agent",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "System prompt defining the agent's role and expertise",
                    },
                    "llm_provider": {
                        "type": "string",
                        "description": "LLM provider override (anthropic, openai, ollama)",
                    },
                    "llm_model": {
                        "type": "string",
                        "description": "LLM model override",
                    },
                    "tool_allow": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tool names/groups to allow (empty = all)",
                    },
                    "tool_deny": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tool names/groups to deny",
                    },
                    "max_tool_rounds": {
                        "type": "integer",
                        "description": "Max tool-use rounds (default 25)",
                    },
                    "autonomy_level": {
                        "type": "integer",
                        "description": "Autonomy level 0-3 (capped at parent's level)",
                    },
                    "workspace_root": {
                        "type": "string",
                        "description": "Workspace directory (relative to parent workspace)",
                    },
                },
                "required": ["agent_id", "display_name", "system_prompt"],
            },
            risk_tier=RiskTier.WRITE_LOCAL,
            group="agents",
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        agent_id = arguments["agent_id"]
        display_name = arguments["display_name"]
        system_prompt = arguments["system_prompt"]

        # Check if agent already exists
        if self._registry.get(agent_id):
            return ToolResult.fail(f"Agent '{agent_id}' already exists.")

        # Get parent agent for constraint checking
        parent = self._registry.get(context.agent_id)
        parent_autonomy = parent.autonomy_level if parent else 1

        # Validate autonomy level (capped at parent's level)
        requested_autonomy = arguments.get("autonomy_level", parent_autonomy)
        autonomy = min(requested_autonomy, parent_autonomy)

        # Validate workspace (must be within parent workspace)
        workspace = arguments.get("workspace_root")
        if workspace:
            parent_workspace = Path(context.workspace_root).resolve()
            child_workspace = (parent_workspace / workspace).resolve()
            try:
                child_workspace.relative_to(parent_workspace)
            except ValueError:
                return ToolResult.fail(
                    "Child workspace must be within parent workspace."
                )
            workspace = str(child_workspace)
        else:
            workspace = context.workspace_root

        # Check nesting depth
        depth = 0
        current = parent
        while current and current.parent_agent_id:
            depth += 1
            current = self._registry.get(current.parent_agent_id)
        if depth >= self._max_depth:
            return ToolResult.fail(
                f"Maximum agent nesting depth ({self._max_depth}) reached."
            )

        # Create the agent definition
        definition = AgentDefinition(
            agent_id=agent_id,
            display_name=display_name,
            system_prompt=system_prompt,
            llm_provider=arguments.get("llm_provider"),
            llm_model=arguments.get("llm_model"),
            tool_allow=arguments.get("tool_allow", []),
            tool_deny=arguments.get("tool_deny", []),
            max_tool_rounds=arguments.get("max_tool_rounds", 25),
            autonomy_level=autonomy,
            workspace_root=workspace,
            parent_agent_id=context.agent_id,
        )

        self._registry.register(definition)

        return ToolResult.ok(
            f"Agent '{agent_id}' ({display_name}) created. "
            f"Autonomy: {autonomy}, workspace: {workspace}"
        )
