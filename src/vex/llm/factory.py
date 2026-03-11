"""LLM provider factory — creates clients from config."""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from .anthropic import AnthropicClient
from .base import LlmClient
from .ollama import OllamaClient
from .openai import OpenAiClient

logger = logging.getLogger(__name__)


def ensure_ollama_model(model: str, base_url: str = "http://localhost:11434") -> None:
    """Check if the Ollama model is available locally; pull it if not.

    Uses the Ollama REST API to check the local model list, then falls back
    to ``ollama pull`` if the model is missing.
    """
    try:
        import urllib.request
        import json

        api_url = base_url.rstrip("/v1").rstrip("/") + "/api/tags"
        with urllib.request.urlopen(api_url, timeout=5) as resp:
            data = json.loads(resp.read())
        available = {m["name"] for m in data.get("models", [])}
        # Normalise: "qwen3:30b-a3b" matches "qwen3:30b-a3b" exactly; also
        # check without tag in case the user specified just a bare name.
        if model in available or model.split(":")[0] in {n.split(":")[0] for n in available}:
            logger.debug("Ollama model '%s' is already available.", model)
            return
    except Exception as e:
        logger.debug("Could not query Ollama model list (%s); will attempt pull.", e)

    logger.warning("Ollama model '%s' not found locally — pulling now (this may take a while)…", model)
    print(f"[vex] Ollama model '{model}' not found — pulling… (this may take a while)", flush=True)
    try:
        subprocess.run(["ollama", "pull", model], check=True)
        print(f"[vex] Model '{model}' ready.", flush=True)
    except FileNotFoundError:
        logger.error("'ollama' command not found. Is Ollama installed and on PATH?")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to pull Ollama model '%s': %s", model, exc)
        sys.exit(1)


def create_llm_client(
    config: dict[str, Any],
    provider_override: str | None = None,
    model_override: str | None = None,
) -> LlmClient:
    """Create an LLM client from configuration.

    Config expects:
        provider: str  — "anthropic", "openai", "ollama"
        model: str     — model name
        Plus provider-specific keys under config[provider].

    Overrides allow sub-agents to use different providers/models.
    """
    provider = provider_override or config.get("provider", "anthropic")
    # Model precedence: explicit override > top-level [llm].model >
    # provider-specific [llm.<provider>].model > built-in default.
    _provider_model = config.get(provider, {}).get("model")
    _defaults = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-4o", "ollama": "llama3.2"}
    model = (
        model_override
        or config.get("model")
        or _provider_model
        or _defaults.get(provider, "gpt-4o")
    )

    if provider == "anthropic":
        provider_config = config.get("anthropic", {})
        return AnthropicClient(
            api_key=provider_config.get("api_key"),
            model=model,
            max_tokens=provider_config.get("max_tokens", 8192),
        )

    if provider == "openai":
        provider_config = config.get("openai", {})
        return OpenAiClient(
            api_key=provider_config.get("api_key"),
            model=model,
            base_url=provider_config.get("base_url"),
            max_tokens=provider_config.get("max_tokens", 8192),
        )

    if provider == "ollama":
        provider_config = config.get("ollama", {})
        base_url = provider_config.get("base_url", "http://localhost:11434/v1")
        ensure_ollama_model(model, base_url)
        return OllamaClient(
            model=model,
            base_url=base_url,
            max_tokens=provider_config.get("max_tokens", 8192),
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
