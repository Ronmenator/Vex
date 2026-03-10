"""Main CLI application — the Vex REPL."""

from __future__ import annotations

import asyncio
import os
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from vex.agent.conversation import Conversation
from vex.agent.definition import AgentDefinition
from vex.agent.loop import AgentLoop, ToolCallEvent
from vex.agent.registry import AgentRegistry
from vex.agent.strategy import StrategyAdvisor
from vex.audit.log import AuditLog
from vex.cli.approvals import ApprovalManager
from vex.cli.renderer import Renderer
from vex.communication.feedback import FeedbackCollector
from vex.config.loader import load_config
from vex.context.preferences import PreferenceStore
from vex.debug.mode import DebugMode
from vex.llm.base import StreamEvent
from vex.llm.factory import create_llm_client
from vex.metrics.analyzer import MetricsAnalyzer
from vex.metrics.collector import MetricsCollector
from vex.safety.conflict import ConflictDetector
from vex.tools.agent_ask import AgentAskTool
from vex.tools.agent_create import AgentCreateTool
from vex.tools.agent_delegate import AgentDelegateTool
from vex.tools.file_batch import FileBatchTool
from vex.tools.file_diff import FileDiffTool
from vex.tools.file_edit import FileEditTool
from vex.tools.file_read import FileReadTool
from vex.tools.file_write import FileWriteTool
from vex.tools.glob_tool import GlobTool
from vex.tools.grep_tool import GrepTool
from vex.tools.memory import MemoryStore, MemoryTool
from vex.tools.middleware import (
    DryRunMiddleware,
    MetricsMiddleware,
    RetryMiddleware,
    TimeoutMiddleware,
    ToolExecutor,
)
from vex.tools.registry import ToolRegistry
from vex.tools.shell import ShellTool
from vex.tools.browser import BrowserTool
from vex.tools.web_fetch import WebFetchTool
from vex.tools.web_search import WebSearchTool
from vex.tools.net_broadcast import NetBroadcastTool
from vex.tools.net_constitution import NetConstitutionTool
from vex.tools.net_discover import NetDiscoverTool
from vex.tools.net_group import NetGroupTool
from vex.tools.net_jobs import NetJobsTool
from vex.tools.net_peers import NetPeersTool
from vex.tools.net_request import NetRequestTool
from vex.tools.net_wiki import NetWikiTool


def build_tool_registry(
    agent_registry: AgentRegistry,
    delegate_func: object,
    ask_func: object,
    memory_store: MemoryStore,
    max_agent_depth: int = 3,
    get_node: object | None = None,
) -> ToolRegistry:
    """Register all available tools."""
    registry = ToolRegistry()
    # Read-only tools
    registry.register(FileReadTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(FileDiffTool())
    # Write tools
    registry.register(FileWriteTool())
    registry.register(FileEditTool())
    registry.register(FileBatchTool())
    registry.register(ShellTool())
    # Web tools
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(BrowserTool())
    # Memory
    registry.register(MemoryTool(memory_store))
    # Agent meta-tools
    registry.register(AgentCreateTool(agent_registry, max_depth=max_agent_depth))
    registry.register(AgentDelegateTool(delegate_func))
    registry.register(AgentAskTool(ask_func))
    # Network tools (VexNet)
    if get_node is not None:
        registry.register(NetDiscoverTool(get_node))
        registry.register(NetRequestTool(get_node))
        registry.register(NetBroadcastTool(get_node))
        registry.register(NetPeersTool(get_node))
        registry.register(NetJobsTool(get_node))
        registry.register(NetWikiTool(get_node))
        registry.register(NetGroupTool(get_node))
        registry.register(NetConstitutionTool(get_node))
    # Discover plugins
    registry.discover_plugins()
    return registry


def build_tool_executor(debug: bool = False) -> ToolExecutor:
    """Build the middleware-based tool executor."""
    executor = ToolExecutor()
    executor.add(DryRunMiddleware())
    executor.add(TimeoutMiddleware())
    executor.add(RetryMiddleware())
    if debug:
        executor.add(MetricsMiddleware())
    return executor


async def run_repl() -> None:
    """Run the interactive REPL."""
    console = Console()
    renderer = Renderer(console)

    # Load config
    config = load_config()
    llm_config = config.get("llm", {})
    security_config = config.get("security", {})
    audit_config = config.get("audit", {})
    debug_config = config.get("debug", {})

    provider = llm_config.get("provider", "anthropic")
    model = llm_config.get("model", "claude-sonnet-4-20250514")
    workspace = os.getcwd()

    # Create LLM client
    try:
        llm = create_llm_client(llm_config)
    except Exception as e:
        renderer.print_error(f"Failed to create LLM client: {e}")
        sys.exit(1)

    # Create audit log
    audit_dir = os.path.join(workspace, audit_config.get("directory", ".vex/audit"))
    audit_log = AuditLog(
        directory=audit_dir,
        enabled=audit_config.get("enabled", True),
    )

    # Create approval manager
    approval_manager = ApprovalManager(renderer)

    # Create memory store
    memory_dir = os.path.join(workspace, ".vex", "memory")
    memory_store = MemoryStore(memory_dir)

    # Create agent registry
    agent_registry = AgentRegistry()

    # Debug mode
    debug_mode = DebugMode(console)
    if debug_config.get("enabled", False):
        debug_mode.enable()

    # Metrics
    metrics_collector = MetricsCollector(workspace)
    metrics_analyzer = MetricsAnalyzer(metrics_collector)
    strategy_advisor = StrategyAdvisor(metrics_analyzer)

    # Conflict detector
    conflict_detector = ConflictDetector()

    # Feedback collector
    feedback_collector = FeedbackCollector(workspace)

    # Preferences
    preferences = PreferenceStore(workspace)

    # VexNet (conditional)
    network_config = config.get("network", {})
    vexnet_client = None

    if network_config.get("enabled", False):
        try:
            from vex.network.client import VexNetClient

            vexnet_client = VexNetClient.from_config(
                network_config,
                data_dir=os.path.join(workspace, ".vex", "network"),
            )
            renderer.print_info(
                f"  [VexNet enabled: {vexnet_client.identity.display_name} "
                f"-> {network_config.get('server_url', '?')}]"
            )
        except Exception as e:
            renderer.print_error(f"Failed to initialize VexNet: {e}")
            vexnet_client = None

    def _get_node():
        return vexnet_client

    # Tool executor with middleware
    tool_executor = build_tool_executor(debug=debug_mode.enabled)

    # Create default agent definition
    dry_run = security_config.get("dry_run", False)
    agent_def = AgentDefinition(
        agent_id="default",
        display_name="Vex",
        autonomy_level=security_config.get("autonomy_level", 1),
        max_tool_rounds=security_config.get("max_tool_rounds", 25),
        workspace_root=workspace,
        dry_run=dry_run,
    )
    agent_registry.register(agent_def)

    # Load persisted agent configs
    try:
        from vex.config.api import AgentConfigAPI

        agent_api = AgentConfigAPI(workspace, agent_registry)
        agent_api.load_persisted()
    except Exception:
        agent_api = None

    # --- Delegation infrastructure ---

    async def delegate_to_agent(agent_id: str, task: str) -> str:
        """Run a sub-agent and return its response text."""
        target_def = agent_registry.get(agent_id)
        if not target_def:
            raise ValueError(f"Agent '{agent_id}' not found.")

        sub_llm = create_llm_client(
            llm_config,
            provider_override=target_def.llm_provider,
            model_override=target_def.llm_model,
        )

        sub_agent = AgentLoop(
            definition=target_def,
            llm=sub_llm,
            tool_registry=tool_registry,
            approval_callback=approval_manager.check_approval,
            audit_log=audit_log,
            tool_executor=tool_executor,
            metrics_collector=metrics_collector,
            conflict_detector=conflict_detector,
            debug_mode=debug_mode,
        )

        sub_conversation = Conversation()
        response_parts: list[str] = []

        async for event in sub_agent.run(task, sub_conversation):
            if isinstance(event, StreamEvent) and event.text_delta:
                response_parts.append(event.text_delta)
            elif isinstance(event, ToolCallEvent):
                if event.result is None:
                    renderer.render_tool_call(event)
                else:
                    renderer.render_tool_result(event)

        return "".join(response_parts) or "Agent completed without response."

    async def ask_user(question: str) -> str:
        """Prompt the user with a question and return their answer."""
        renderer.console.print()
        renderer.console.print(f"  [bold bright_cyan]Agent asks:[/] {question}")
        answer = renderer.console.input("  Your answer: ").strip()
        return answer

    # Build tool registry with delegation wired in
    max_depth = security_config.get("max_agent_depth", 3)
    tool_registry = build_tool_registry(
        agent_registry, delegate_to_agent, ask_user, memory_store, max_depth,
        get_node=_get_node if vexnet_client else None,
    )

    # Build prompt enhancers
    prompt_enhancers = []
    if vexnet_client:
        from vex.network.prompt import VexNetPromptEnhancer
        prompt_enhancers.append(VexNetPromptEnhancer(_get_node))

    # Create agent loop
    agent = AgentLoop(
        definition=agent_def,
        llm=llm,
        tool_registry=tool_registry,
        approval_callback=approval_manager.check_approval,
        audit_log=audit_log,
        tool_executor=tool_executor,
        metrics_collector=metrics_collector,
        conflict_detector=conflict_detector,
        debug_mode=debug_mode,
        strategy_advisor=strategy_advisor,
        prompt_enhancers=prompt_enhancers,
    )

    # Create conversation
    conversation = Conversation()

    # Setup prompt with history
    history_dir = os.path.join(os.path.expanduser("~"), ".vex")
    os.makedirs(history_dir, exist_ok=True)
    history_file = os.path.join(history_dir, "history")

    session: PromptSession[str] = PromptSession(
        history=FileHistory(history_file),
    )

    # Connect to VexNet server if enabled
    if vexnet_client:
        try:
            await vexnet_client.connect()
        except Exception as e:
            renderer.print_error(f"VexNet connection failed: {e}")
            vexnet_client = None

    renderer.print_welcome(provider, model, workspace)
    if dry_run:
        renderer.print_info("  [DRY RUN mode enabled — no write operations will execute]")
    if debug_mode.enabled:
        renderer.print_info("  [DEBUG mode enabled]")
    if vexnet_client:
        renderer.print_info("  [VexNet active — use /tools to see net.* tools]")

    tool_call_count = 0  # Track for feedback prompts

    while True:
        try:
            user_input = await session.prompt_async(
                "> ",
                multiline=False,
            )
        except (EOFError, KeyboardInterrupt):
            renderer.print_info("\nGoodbye.")
            # Disconnect from VexNet
            if vexnet_client:
                await vexnet_client.disconnect()
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle commands
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd in ("/quit", "/exit", "/q"):
                renderer.print_info("Goodbye.")
                break
            elif cmd == "/clear":
                conversation.clear()
                approval_manager.reset()
                renderer.print_info("Conversation cleared.")
                continue
            elif cmd == "/tools":
                tools = tool_registry.list_all()
                for t in tools:
                    renderer.print_info(
                        f"  {t.name} [{t.risk_tier.name}] — {t.description}"
                    )
                continue
            elif cmd == "/agents":
                agents = agent_registry.list_all()
                for a in agents:
                    renderer.print_info(
                        f"  {a.agent_id} ({a.display_name}) "
                        f"autonomy={a.autonomy_level}"
                    )
                continue
            elif cmd.startswith("/autonomy"):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].isdigit():
                    level = int(parts[1])
                    if 0 <= level <= 3:
                        agent_def = AgentDefinition(
                            agent_id=agent_def.agent_id,
                            display_name=agent_def.display_name,
                            system_prompt=agent_def.system_prompt,
                            autonomy_level=level,
                            max_tool_rounds=agent_def.max_tool_rounds,
                            workspace_root=agent_def.workspace_root,
                            dry_run=agent_def.dry_run,
                        )
                        agent_registry.register(agent_def)
                        agent = AgentLoop(
                            definition=agent_def,
                            llm=llm,
                            tool_registry=tool_registry,
                            approval_callback=approval_manager.check_approval,
                            audit_log=audit_log,
                            tool_executor=tool_executor,
                            metrics_collector=metrics_collector,
                            conflict_detector=conflict_detector,
                            debug_mode=debug_mode,
                            strategy_advisor=strategy_advisor,
                        )
                        renderer.print_info(f"Autonomy level set to {level}.")
                    else:
                        renderer.print_error("Autonomy level must be 0-3.")
                else:
                    renderer.print_info(
                        f"Current autonomy level: {agent_def.autonomy_level}"
                    )
                continue
            elif cmd == "/audit":
                entries = audit_log.query_recent(10)
                if not entries:
                    renderer.print_info("No audit entries.")
                else:
                    for e in entries:
                        renderer.print_info(
                            f"  [{e.timestamp}] {e.event_type}: {e.tool_name or ''} "
                            f"({e.result_summary or e.error or ''})"
                        )
                continue
            elif cmd == "/debug":
                state = debug_mode.toggle()
                renderer.print_info(f"Debug mode {'enabled' if state else 'disabled'}.")
                continue
            elif cmd == "/dryrun":
                agent_def = AgentDefinition(
                    agent_id=agent_def.agent_id,
                    display_name=agent_def.display_name,
                    system_prompt=agent_def.system_prompt,
                    autonomy_level=agent_def.autonomy_level,
                    max_tool_rounds=agent_def.max_tool_rounds,
                    workspace_root=agent_def.workspace_root,
                    dry_run=not agent_def.dry_run,
                )
                agent_registry.register(agent_def)
                agent = AgentLoop(
                    definition=agent_def,
                    llm=llm,
                    tool_registry=tool_registry,
                    approval_callback=approval_manager.check_approval,
                    audit_log=audit_log,
                    tool_executor=tool_executor,
                    metrics_collector=metrics_collector,
                    conflict_detector=conflict_detector,
                    debug_mode=debug_mode,
                    strategy_advisor=strategy_advisor,
                )
                renderer.print_info(
                    f"Dry-run mode {'enabled' if agent_def.dry_run else 'disabled'}."
                )
                continue
            elif cmd == "/metrics":
                stats = metrics_collector.get_tool_stats()
                if stats["total"] == 0:
                    renderer.print_info("No metrics collected yet.")
                else:
                    renderer.print_info(
                        f"  Total tool calls: {stats['total']}, "
                        f"success rate: {stats['success_rate']:.0%}, "
                        f"avg duration: {stats['avg_duration_s']:.2f}s"
                    )
                    errors = metrics_collector.get_common_errors(5)
                    if errors:
                        renderer.print_info("  Common errors:")
                        for e in errors:
                            renderer.print_info(f"    {e['pattern']}: {e['count']}x")
                continue
            elif cmd == "/plugins":
                from vex.plugins.loader import PluginLoader

                loader = PluginLoader()
                plugins = loader.discover()
                if not plugins:
                    renderer.print_info("No plugins found.")
                else:
                    for p in plugins:
                        renderer.print_info(f"  {p.schema.name} — {p.schema.description}")
                if loader.errors:
                    for err in loader.errors:
                        renderer.print_error(f"  {err}")
                continue
            elif cmd == "/feedback":
                stats = feedback_collector.get_stats()
                renderer.print_info(
                    f"  Feedback: {stats['positive']} positive, "
                    f"{stats['negative']} negative, {stats['total']} total"
                )
                continue
            elif cmd.startswith("/pref"):
                parts = user_input.split(maxsplit=2)
                if len(parts) == 1:
                    # Show all preferences
                    prefs = preferences.all()
                    if not prefs:
                        renderer.print_info("No preferences set.")
                    else:
                        for k, v in prefs.items():
                            renderer.print_info(f"  {k}: {v}")
                elif len(parts) == 3:
                    key, value = parts[1], parts[2]
                    preferences.set(key, value)
                    renderer.print_info(f"Preference '{key}' set.")
                else:
                    renderer.print_info("Usage: /pref [key] [value]")
                continue
            else:
                renderer.print_error(f"Unknown command: {user_input}")
                continue

        # Run agent
        try:
            renderer.start_streaming()
            console.print()  # Blank line before response
            tool_call_count = 0

            async for event in agent.run(user_input, conversation):
                if isinstance(event, StreamEvent):
                    if event.text_delta:
                        renderer.stream_token(event.text_delta)
                elif isinstance(event, ToolCallEvent):
                    renderer.end_streaming()
                    if event.result is None:
                        renderer.render_tool_call(event)
                    else:
                        renderer.render_tool_result(event)
                        tool_call_count += 1
                    renderer.start_streaming()

            renderer.end_streaming()
            console.print()  # Blank line after response

            # Prompt for feedback after complex operations (5+ tool calls)
            if tool_call_count >= 5:
                rating = renderer.render_feedback_prompt()
                if rating:
                    feedback_collector.record(rating, context=user_input[:200])

        except KeyboardInterrupt:
            renderer.end_streaming()
            renderer.print_info("\n[Interrupted]")
        except Exception as e:
            renderer.end_streaming()
            renderer.print_error(str(e))


def main() -> None:
    """Entry point for the vex CLI.

    Usage:
        vex              — interactive REPL
        vex --telegram   — start Telegram bot
    """
    import argparse

    parser = argparse.ArgumentParser(description="Vex — Autonomous AI Agent")
    parser.add_argument(
        "--telegram", action="store_true", help="Start as Telegram bot instead of REPL"
    )
    parser.add_argument("--token", help="Telegram bot token (with --telegram)")
    parser.add_argument("--workspace", help="Workspace directory (default: cwd)")
    args = parser.parse_args()

    if args.telegram:
        import logging

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        from vex.telegram.bot import run_bot

        try:
            run_bot(token=args.token, workspace=args.workspace)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            asyncio.run(run_repl())
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
