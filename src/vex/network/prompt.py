"""VexNet prompt enhancer -- injects VexNet context into the bot's system prompt."""

from __future__ import annotations

from typing import Any


class VexNetPromptEnhancer:
    """Prompt enhancer that appends VexNet guide and status to the system prompt.

    Plugs into AgentLoop's prompt_enhancers list. Called once per turn to give
    the bot up-to-date context about its VexNet identity and network state.
    """

    def __init__(self, get_client):
        self._get_client = get_client

    def enhance_prompt(self, system_prompt: str) -> str:
        client = self._get_client()
        if not client or not client.enabled:
            return system_prompt

        from vex.network.guide import build_vexnet_prompt_section

        section = build_vexnet_prompt_section(client)
        if section:
            return system_prompt + "\n\n" + section
        return system_prompt
