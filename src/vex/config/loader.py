"""Configuration loader — reads vex.toml with env var overrides."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration from vex.toml with environment variable overrides.

    Search order for config file:
    1. Explicit path
    2. ./vex.toml (current directory)
    3. ~/.vex/config.toml (user home)

    Environment variable overrides:
    - ANTHROPIC_API_KEY -> llm.anthropic.api_key
    - OPENAI_API_KEY -> llm.openai.api_key
    - VEX_LLM_PROVIDER -> llm.provider
    - VEX_LLM_MODEL -> llm.model
    - VEX_AUTONOMY_LEVEL -> security.autonomy_level
    """
    config: dict[str, Any] = {}

    # Load .env file if present (before config, so ${VAR} refs can resolve)
    _load_dotenv()

    # Find and load config file
    if config_path:
        paths = [Path(config_path)]
    else:
        paths = [
            Path.cwd() / "vex.toml",
            Path.home() / ".vex" / "config.toml",
        ]

    for path in paths:
        if path.is_file():
            with open(path, "rb") as f:
                config = tomllib.load(f)
            break

    # Resolve ${ENV_VAR} references in string values
    _resolve_env_vars(config)

    # Ensure nested dicts exist
    config.setdefault("llm", {})
    config["llm"].setdefault("anthropic", {})
    config["llm"].setdefault("openai", {})
    config["llm"].setdefault("ollama", {})
    config.setdefault("security", {})
    config.setdefault("audit", {})
    config.setdefault("plugins", {})
    config.setdefault("debug", {})
    config.setdefault("telegram", {})

    # Network (VexNet) defaults
    config.setdefault("network", {})
    net = config["network"]
    net.setdefault("enabled", False)
    net.setdefault("display_name", "Vex-Bot")
    net.setdefault("listen_port", 9120)
    net.setdefault("capabilities", ["general"])
    net.setdefault("discoverable", True)
    net.setdefault("registry", {})
    net.setdefault("security", {})
    net_sec = net["security"]
    net_sec.setdefault("allow_unknown_peers", False)
    net_sec.setdefault("max_concurrent_tasks", 3)
    net_sec.setdefault("max_task_timeout", 300)
    net_sec.setdefault("sandbox_directory", ".vex/network/sandbox")
    net_sec.setdefault("default_policy", {})
    dp = net_sec["default_policy"]
    dp.setdefault("trust_level", 0)
    dp.setdefault("max_risk_tier", 0)
    dp.setdefault("rate_limit", 5)
    net.setdefault("hub", {})
    hub = net["hub"]
    hub.setdefault("enabled", False)
    hub.setdefault("host", "0.0.0.0")
    hub.setdefault("port", 9121)
    hub.setdefault("allow_human_invites", False)
    net.setdefault("peers", [])

    # Environment variable overrides
    if api_key := os.environ.get("ANTHROPIC_API_KEY"):
        config["llm"]["anthropic"]["api_key"] = api_key

    if api_key := os.environ.get("OPENAI_API_KEY"):
        config["llm"]["openai"]["api_key"] = api_key

    if provider := os.environ.get("VEX_LLM_PROVIDER"):
        config["llm"]["provider"] = provider

    if model := os.environ.get("VEX_LLM_MODEL"):
        config["llm"]["model"] = model

    if level := os.environ.get("VEX_AUTONOMY_LEVEL"):
        try:
            config["security"]["autonomy_level"] = int(level)
        except ValueError:
            pass

    if os.environ.get("VEX_DRY_RUN", "").lower() in ("1", "true", "yes"):
        config["security"]["dry_run"] = True

    if os.environ.get("VEX_DEBUG", "").lower() in ("1", "true", "yes"):
        config["debug"]["enabled"] = True

    if bot_token := (
        os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    ):
        config["telegram"]["bot_token"] = bot_token

    # VexNet env var overrides
    if os.environ.get("VEXNET_ENABLED", "").lower() in ("1", "true", "yes"):
        config["network"]["enabled"] = True

    if name := os.environ.get("VEXNET_DISPLAY_NAME"):
        config["network"]["display_name"] = name

    if port := os.environ.get("VEXNET_PORT"):
        try:
            config["network"]["listen_port"] = int(port)
        except ValueError:
            pass

    if os.environ.get("VEXNET_HUB_ENABLED", "").lower() in ("1", "true", "yes"):
        config["network"]["hub"]["enabled"] = True

    if hub_port := os.environ.get("VEXNET_HUB_PORT"):
        try:
            config["network"]["hub"]["port"] = int(hub_port)
        except ValueError:
            pass

    return config


def _load_dotenv() -> None:
    """Load .env file into os.environ (won't override existing vars)."""
    for search_dir in [Path.cwd(), Path(__file__).resolve().parent.parent.parent.parent]:
        env_file = search_dir / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            except OSError:
                pass
            return  # Only load the first .env found


_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(obj: Any) -> Any:
    """Recursively resolve ${ENV_VAR} references in string values."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            obj[key] = _resolve_env_vars(value)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            obj[i] = _resolve_env_vars(value)
    elif isinstance(obj, str) and "${" in obj:
        def _replace(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(0))
        obj = _ENV_VAR_RE.sub(_replace, obj)
    return obj
