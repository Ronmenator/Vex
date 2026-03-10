# Vex

Autonomous AI agent system that acts on your instructions, builds other agents dynamically, executes commands, and writes code with graduated autonomy.

## Quick Start

```bash
# Install (requires Python 3.12+)
pip install -e .

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Launch the REPL
vex
```

## Key Features

- **Agents build agents** — the running agent dynamically creates specialist sub-agents at runtime via `agent.create` and delegates tasks to them
- **Graduated autonomy** — 4-level trust system (0=ask everything, 1=ask risky, 2=ask destructive only, 3=full auto)
- **Multi-provider LLM** — Anthropic Claude, OpenAI (and compatible APIs), Ollama local models
- **Coding workflow** — plan → code → test → iterate emerges naturally from the tool set
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

| Command | Description |
|---------|-------------|
| `/quit`, `/exit`, `/q` | Exit Vex |
| `/clear` | Clear conversation history |
| `/tools` | List all registered tools |
| `/agents` | List all registered agents |
| `/autonomy [level]` | Get or set autonomy level (0-3) |
| `/audit` | Show recent audit log entries |

## Configuration

Vex reads configuration from `vex.toml` in the current directory, falling back to `~/.vex/config.toml`.

```toml
[llm]
provider = "anthropic"           # anthropic, openai, ollama
model = "claude-sonnet-4-20250514"
api_key = "sk-ant-..."           # or use environment variables

[llm.openai]
base_url = "https://api.openai.com/v1"  # override for compatible APIs

[security]
autonomy_level = 1               # 0-3
max_tool_rounds = 25
max_agent_depth = 3

[audit]
enabled = true
directory = ".vex/audit"
```

### Environment Variables

| Variable | Overrides |
|----------|-----------|
| `ANTHROPIC_API_KEY` | `llm.api_key` (when provider is anthropic) |
| `OPENAI_API_KEY` | `llm.api_key` (when provider is openai) |
| `VEX_PROVIDER` | `llm.provider` |
| `VEX_MODEL` | `llm.model` |
| `VEX_AUTONOMY` | `security.autonomy_level` |

## Project Structure

```
src/vex/
├── cli/            # REPL, rendering, approval prompts
├── agent/          # Agent loop, planner, definitions, registry
├── llm/            # LLM client protocol + providers
├── tools/          # All tool implementations
├── coding/         # Test runner, workflow orchestration
├── security/       # Policy engine, workspace sandboxing
├── audit/          # Append-only JSONL audit log
└── config/         # TOML config loader
```

## Requirements

- Python 3.12+
- An API key for at least one LLM provider (Anthropic, OpenAI, or a running Ollama instance)
