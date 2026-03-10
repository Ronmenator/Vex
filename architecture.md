# Vex Architecture

## System Overview

```
┌─────────────────────────────────────────────────┐
│                   CLI (REPL)                     │
│  prompt_toolkit input → Rich streaming output    │
├─────────────────────────────────────────────────┤
│                 Agent Loop                       │
│  stream LLM → execute tools → feed back → repeat│
├──────────┬──────────────┬───────────────────────┤
│ LLM      │ Tool         │ Security              │
│ Clients  │ Registry     │ Policy + Sandbox      │
├──────────┼──────────────┼───────────────────────┤
│anthropic │ fs tools     │ PolicyEngine          │
│openai    │ web tools    │ WorkspaceSandbox      │
│ollama    │ agent tools  │ ApprovalManager       │
│          │ memory       │ AuditLog              │
└──────────┴──────────────┴───────────────────────┘
```

## Core Abstractions

### Agent Loop (`agent/loop.py`)

The heart of the system. A simple while loop — not a graph, not a chain:

1. Build messages (system prompt + conversation history + user message)
2. Call LLM with tool definitions (streaming)
3. If response has no tool calls → yield final text, return
4. For each tool call:
   - Policy check (does this need approval at the current autonomy level?)
   - Approval gate (prompt user if needed)
   - Execute tool
   - Audit log the call and result
5. Append tool results to messages, go to step 2
6. Cap at `max_tool_rounds` (default 25) to prevent runaway loops

The loop yields two event types:
- `StreamEvent` — text deltas for streaming output
- `ToolCallEvent` — yielded twice per tool: once as header (no result), once as completion (with result)

### Agent Definition (`agent/definition.py`)

```python
@dataclass
class AgentDefinition:
    agent_id: str
    display_name: str
    system_prompt: str | None        # None = use default
    llm_provider: str | None         # None = inherit from parent
    llm_model: str | None
    tool_allow: list[str]            # empty = all allowed
    tool_deny: list[str]
    max_tool_rounds: int             # default 25
    autonomy_level: int              # 0-3
    workspace_root: str | None
    parent_agent_id: str | None
```

The default system prompt includes coding workflow instructions (plan → implement → test → iterate).

### LLM Client Protocol (`llm/base.py`)

```python
class LlmClient(Protocol):
    async def chat(self, messages, tools, **kwargs) -> LlmResponse
    async def stream(self, messages, tools, **kwargs) -> AsyncIterator[StreamEvent]
```

Three implementations:
- **AnthropicClient** — Claude models, native tool_use blocks, input_json_delta streaming
- **OpenAiClient** — OpenAI and compatible APIs, function calling format, tool call assembly by index
- **OllamaClient** — Extends OpenAiClient with local defaults (localhost:11434)

### Tool System (`tools/base.py`)

```python
class Tool(Protocol):
    schema: ToolSchema
    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult
```

Each tool declares a `ToolSchema` with:
- `name` — unique identifier
- `description` — for the LLM
- `parameters` — JSON Schema for arguments
- `risk_tier` — READ_ONLY, WRITE_LOCAL, WRITE_EXTERNAL, or DESTRUCTIVE
- `group` — for filtering (fs, web, agents, memory, runtime)

`ToolResult` is either success (`ok(output)`) or failure (`fail(error)`).

---

## Security Model

### Risk Tiers

| Tier | Value | Tools | What it means |
|------|-------|-------|---------------|
| READ_ONLY | 0 | file_read, glob, grep, agent.ask | No side effects |
| WRITE_LOCAL | 1 | file_write, file_edit, memory, agent.create | Modifies local state |
| WRITE_EXTERNAL | 2 | web_search, web_fetch, agent.delegate | External network or delegation |
| DESTRUCTIVE | 3 | shell | Arbitrary command execution |

### Autonomy Levels

| Level | Behavior |
|-------|----------|
| 0 | Every tool call requires approval |
| 1 | READ_ONLY + WRITE_LOCAL auto-approved; WRITE_EXTERNAL + DESTRUCTIVE need approval |
| 2 | Only DESTRUCTIVE needs approval |
| 3 | Full autonomy — no approval prompts |

The policy engine (`security/policy.py`) evaluates each tool call against the agent's autonomy level and returns ALLOW, DENY, or REQUIRES_APPROVAL.

### Sub-Agent Constraints

When an agent creates a sub-agent via `agent.create`:
- **Autonomy ceiling**: child autonomy ≤ parent autonomy
- **Workspace nesting**: child workspace must be inside parent workspace
- **Depth limit**: default max 3 levels of nesting
- **Tool inheritance**: child tools ⊆ parent's allowed tools

### Workspace Sandboxing

`WorkspaceSandbox` validates all file paths against the workspace root using `Path.resolve()` + `relative_to()`. Blocks path traversal (e.g., `../../etc/passwd`).

### Audit Log

Append-only JSONL files (one per day) in `.vex/audit/`. Every tool call is logged with:
- Timestamp, agent ID, correlation ID
- Tool name, arguments, result summary
- Automatic secret redaction (API keys, tokens, passwords)

---

## Meta-Agent System

### How Agents Build Agents

```
User: "Build a scraper and a Chrome extension for the data"

Main Agent:
  → agent.create(id="scraper", prompt="Python scraping specialist...")
  → agent.create(id="chrome-ext", prompt="Chrome extension developer...")
  → agent.delegate(id="scraper", task="Build a scraper for ...")
  → agent.delegate(id="chrome-ext", task="Build a Chrome extension...")
  → Synthesize results
```

### agent.create

Creates a new `AgentDefinition` in the `AgentRegistry`. The sub-agent doesn't run yet — it's just registered with its configuration (system prompt, tools, LLM provider/model, autonomy level).

### agent.delegate

Sends a task to a registered agent. Creates a fresh `Conversation` + `AgentLoop` for the target, runs it to completion, and returns the response text. The sub-agent's conversation is discarded after (stateless delegation).

### agent.ask

Prompts the user with a question and returns their typed answer. Used when the agent needs clarification or wants to confirm a destructive action.

---

## Task Planner (`agent/planner.py`)

For complex goals, the agent can decompose work into ordered tasks:

1. **Decompose**: LLM breaks the goal into tasks with IDs, descriptions, and dependencies
2. **Execute**: Process tasks in dependency order via `next_ready_task()`
3. **Recover**: On failure → retry with error context → revise plan if still failing
4. **Delegate**: Tasks can be tagged for delegation to sub-agents

```python
@dataclass
class Task:
    task_id: str
    description: str
    depends_on: list[str]
    status: str            # pending, in_progress, done, failed
    delegate_to: str | None
    result: str | None
```

---

## Coding Workflow

Not a separate mode — it emerges from the tool set + system prompt instructions:

1. **Understand**: `glob` / `grep` / `file_read` to explore the codebase
2. **Plan**: Planner decomposes into write → test → fix tasks
3. **Write**: `file_write` / `file_edit` to create and modify code
4. **Test**: `shell` to run tests, `TestRunner` to parse pytest output into structured failures
5. **Iterate**: Read failure → read code → edit → re-test (up to 3 attempts per failure)

The `TestRunner` (`coding/test_runner.py`) parses pytest output to extract individual test failures with file, function name, and error details.

---

## CLI Components

### Renderer (`cli/renderer.py`)

Rich-based output with:
- Token-by-token streaming via `stream_token()`
- Color-coded risk badges: 🟢 READ_ONLY, 🟡 WRITE_LOCAL, 🟣 WRITE_EXTERNAL, 🔴 DESTRUCTIVE
- Tool call display showing name, risk badge, truncated arguments, and result

### Approval Manager (`cli/approvals.py`)

Interactive `[y/n/always]` prompt for tools that require approval:
- `y` — approve this call
- `n` — deny this call
- `always` — auto-approve this tool for the rest of the session

### REPL (`cli/app.py`)

Main loop with `prompt_toolkit` (history, line editing) and slash commands.

---

## Configuration (`config/loader.py`)

Load order:
1. `vex.toml` in current directory
2. `~/.vex/config.toml` (fallback)
3. Environment variable overrides (ANTHROPIC_API_KEY, VEX_PROVIDER, VEX_MODEL, VEX_AUTONOMY)

---

## Data Flow

### Single Turn (No Tools)

```
User input → Conversation.add_user()
           → LLM.stream(messages, tools)
           → yield StreamEvent(text_delta)
           → Conversation.add_assistant(response)
```

### Turn With Tool Calls

```
User input → LLM.stream(messages, tools)
           → response includes tool_calls
           → for each tool_call:
               PolicyEngine.evaluate() → ALLOW / REQUIRES_APPROVAL
               ApprovalManager.check() → approved / denied
               Tool.execute(arguments, context)
               AuditLog.log(entry)
               yield ToolCallEvent(with result)
           → append tool results to messages
           → LLM.stream(messages + results, tools)
           → yield StreamEvent(text_delta)
```

### Sub-Agent Delegation

```
Parent agent → agent.delegate(id, task)
             → create sub LLM client (may differ from parent)
             → create sub AgentLoop + fresh Conversation
             → sub_agent.run(task) → collect response
             → return response text to parent
             → parent continues with result
```
