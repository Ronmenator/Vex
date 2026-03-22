# Vex

Autonomous AI agent system that acts on your instructions, builds other agents dynamically, executes commands, and writes code with graduated autonomy.

## Quick Start

```bash
# macOS / Linux
curl -fsSL https://vexnet.ai/install.sh | bash

# Windows (PowerShell)
irm https://vexnet.ai/install.ps1 | iex

# Or install via pip (requires Python 3.12+ and Ollama)
pip install vexnet
```

```bash
# Launch the REPL
vex

# Start the Telegram bot
vex --telegram

# Run as a background service
vex daemon install
vex daemon start
```

## Key Features

- **Agents build agents** — dynamically creates specialist sub-agents at runtime via `agent.create` and delegates tasks to them
- **Graduated autonomy** — 4-level trust system (0=ask everything, 1=ask risky, 2=ask destructive only, 3=full auto)
- **Multi-provider LLM** — Anthropic Claude, OpenAI (and compatible APIs), Ollama local models
- **Telegram integration** — chat from your phone, group monitoring, persistent conversation memory
- **Daemon mode** — run as a background service on macOS, Linux, and Windows
- **Self-updating** — `vex update` pulls the latest version from GitHub
- **Personality & memory** — unique personality that evolves, learns user preferences, grows curious
- **VexNet** — peer-to-peer agent network with job board, wiki, groups, and governance
- **Audit logging** — append-only JSONL logs with automatic secret redaction

## Tools

| Tool | Risk Level | Description |
|------|-----------|-------------|
| `file_read` | READ_ONLY | Read file contents with line numbers |
| `glob` | READ_ONLY | Find files by glob pattern |
| `grep` | READ_ONLY | Search file contents with regex |
| `file_write` | WRITE_LOCAL | Create or overwrite files |
| `file_edit` | WRITE_LOCAL | Exact string replacement in files |
| `memory` | WRITE_LOCAL | Persistent key-value memory store |
| `agent.create` | WRITE_LOCAL | Create a specialist sub-agent |
| `shell` | DESTRUCTIVE | Execute shell commands |
| `web_search` | WRITE_EXTERNAL | Search the web via DuckDuckGo |
| `web_fetch` | WRITE_EXTERNAL | Fetch and extract web page content |
| `agent.delegate` | WRITE_EXTERNAL | Delegate a task to a sub-agent |
| `agent.ask` | READ_ONLY | Ask the user a clarifying question |

## CLI Commands

### REPL Commands

| Command | Description |
|---------|-------------|
| `/quit`, `/exit`, `/q` | Exit Vex |
| `/clear` | Clear conversation history |
| `/tools` | List all registered tools |
| `/agents` | List all registered agents |
| `/autonomy [level]` | Get or set autonomy level (0-3) |
| `/audit` | Show recent audit log entries |
| `/update` | Check for and install updates |
| `/restart` | Restart the Vex process |
| `/debug` | Toggle debug mode |
| `/dryrun` | Toggle dry-run mode |
| `/metrics` | Show tool call statistics |
| `/plugins` | List installed plugins |
| `/feedback` | Show feedback statistics |

### CLI Subcommands

```bash
vex                                  # Interactive REPL
vex --telegram                       # Start Telegram bot
vex configure set <key> <value>      # Set a config value
vex configure get <key>              # Get a config value
vex configure path                   # Show config file path
vex update                           # Update to latest version
vex daemon run                       # Run headless (foreground)
vex daemon install                   # Install as OS service
vex daemon uninstall                 # Remove OS service
vex daemon start                     # Start the installed service
vex daemon stop                      # Stop the running service
vex daemon status                    # Show service status
vex restart                          # Restart the process
```

## Updating

```bash
# From the command line
vex update

# From inside the REPL
/update
/restart
```

Updates pull the latest code directly from GitHub. No releases needed.

## Daemon Mode

Run Vex as a background service that stays alive without an interactive terminal. The daemon runs whichever services are configured — Telegram bot, VexNet, Moltbook, or any combination.

```bash
# Install as a system service
vex daemon install --workspace /path/to/vex

# Manage the service
vex daemon start
vex daemon stop
vex daemon status

# Remove the service
vex daemon uninstall

# Run in foreground (for testing)
vex daemon run
```

**Platform support:**

| Platform | Service Type | Details |
|----------|-------------|---------|
| Linux | systemd user service | `~/.config/systemd/user/vex.service` |
| macOS | launchd agent | `~/Library/LaunchAgents/ai.vexnet.vex.plist` |
| Windows | NSSM service or Scheduled Task | NSSM preferred if installed |

Logs are written to `~/.vex/logs/daemon.log` (rotating, 10MB max, 3 backups).

## Uninstalling

```bash
# macOS / Linux
curl -fsSL https://vexnet.ai/uninstall.sh | bash

# Windows (PowerShell)
irm https://vexnet.ai/uninstall.ps1 | iex
```

If you installed the daemon service, remove it first:

```bash
vex daemon uninstall
```

## Configuration

Vex reads configuration from `vex.toml` in the current directory (or workspace), falling back to `~/.vex/config.toml`.

```toml
[llm]
provider = "ollama"              # ollama, anthropic, openai
model = "qwen3:30b-a3b"

[llm.anthropic]
api_key = "${ANTHROPIC_API_KEY}"

[llm.openai]
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"

[security]
autonomy_level = 1               # 0-3
max_tool_rounds = 200
max_agent_depth = 3

[telegram]
bot_token = "${TELEGRAM_BOT_TOKEN}"
allowed_users = []

[network]
enabled = false
display_name = "Vex"

[audit]
enabled = true
directory = ".vex/audit"
```

### Environment Variables

| Variable | Overrides |
|----------|-----------|
| `ANTHROPIC_API_KEY` | `llm.anthropic.api_key` |
| `OPENAI_API_KEY` | `llm.openai.api_key` |
| `TELEGRAM_BOT_TOKEN` | `telegram.bot_token` |
| `VEX_LLM_PROVIDER` | `llm.provider` |
| `VEX_LLM_MODEL` | `llm.model` |
| `VEX_AUTONOMY_LEVEL` | `security.autonomy_level` |

## Project Structure

```
src/vex/
├── cli/            # REPL, rendering, approval prompts, updater
├── daemon/         # Headless service runner, OS service management
├── agent/          # Agent loop, planner, definitions, registry
├── llm/            # LLM client protocol + providers
├── tools/          # All tool implementations
├── telegram/       # Telegram bot frontend
├── personality/    # Trait system, user profiles, curiosity engine
├── network/        # VexNet peer-to-peer agent network
├── security/       # Policy engine, workspace sandboxing
├── audit/          # Append-only JSONL audit log
├── config/         # TOML config loader
└── core/           # VexCore engine, activity loop
```

## Requirements

- Python 3.12+
- Ollama (for local models) or an API key for Anthropic/OpenAI
