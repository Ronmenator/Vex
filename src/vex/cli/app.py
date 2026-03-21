"""Main CLI application — the Vex REPL."""

from __future__ import annotations

import asyncio
import os
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console

from vex.agent.conversation import Conversation, RetrievalConversation
from vex.agent.definition import AgentDefinition
from vex.agent.loop import AgentLoop, ToolCallEvent
from vex.cli.approvals import ApprovalManager
from vex.cli.renderer import Renderer
from vex.communication.feedback import FeedbackCollector
from vex.context.preferences import PreferenceStore
from vex.core import VexCore
from vex.llm.base import StreamEvent


async def run_repl() -> None:
    """Run the interactive REPL."""
    console = Console()
    renderer = Renderer(console)

    # Initialize shared engine
    try:
        core = VexCore(workspace=os.getcwd())
    except Exception as e:
        renderer.print_error(f"Failed to initialize Vex: {e}")
        sys.exit(1)

    # Setup prompt with history
    history_dir = os.path.join(os.path.expanduser("~"), ".vex")
    os.makedirs(history_dir, exist_ok=True)
    history_file = os.path.join(history_dir, "history")

    session: PromptSession[str] = PromptSession(
        history=FileHistory(history_file),
    )

    # CLI-specific components (session passed for async-safe input)
    approval_manager = ApprovalManager(renderer, session=session)
    feedback_collector = FeedbackCollector(core.workspace)
    preferences = PreferenceStore(core.workspace)

    # Set up interactive ask function (uses prompt_toolkit for async-safe input)
    async def ask_user(question: str) -> str:
        renderer.console.print()
        renderer.console.print(f"  [bold bright_cyan]Agent asks:[/] {question}")
        answer = await session.prompt_async("  Your answer: ")
        return answer.strip()

    core.set_ask_func(ask_user)

    # User identity (from telegram.allowed_users[0] for cross-frontend continuity)
    user_id = core.cli_user_id
    user_name = "User"

    # Update user profile
    core.user_profiles.get_or_create(user_id, user_name)

    # Create retrieval-based conversation (persistent, shared with Telegram)
    conversation = RetrievalConversation(
        chat_id=user_id,
        chat_history=core.chat_history,
        user_name=user_name,
        chat_title=f"CLI session",
    )

    # Create agent with CLI-specific approval callback
    agent = core.create_agent(
        approval_callback=approval_manager.check_approval,
        user_id=user_id,
        chat_id=user_id,
        is_dm=True,
    )

    # Autonomous activity loop (VexNet + Moltbook, fully autonomous)
    activity_loop = None
    if core.vexnet_client or core.moltbook_client:
        from vex.agent.definition import AUTONOMOUS_SYSTEM_PROMPT
        from vex.core.activity import AutonomousActivityLoop

        async def _auto_approve(tc, schema) -> bool:
            return True

        _bg_agent_def = AgentDefinition(
            agent_id="background",
            display_name="Vex (background)",
            system_prompt=AUTONOMOUS_SYSTEM_PROMPT,
            autonomy_level=3,
            max_tool_rounds=core.agent_def.max_tool_rounds,
            workspace_root=core.workspace,
            dry_run=core.dry_run,
        )

        _bg_agent = AgentLoop(
            definition=_bg_agent_def,
            llm=core.llm,
            tool_registry=core.tool_registry,
            approval_callback=_auto_approve,
            audit_log=core.audit_log,
            tool_executor=core.tool_executor,
            metrics_collector=core.metrics_collector,
            conflict_detector=core.conflict_detector,
            debug_mode=core.debug_mode,
            prompt_enhancers=core.build_prompt_enhancers(),
        )

        async def _run_autonomous_agent(prompt: str) -> str:
            sub_conversation = Conversation()
            parts: list[str] = []
            async for event in _bg_agent.run(prompt, sub_conversation):
                if isinstance(event, StreamEvent) and event.text_delta:
                    parts.append(event.text_delta)
            return "".join(parts)

        activity_interval = core.network_config.get("activity_interval", 300)
        activity_loop = AutonomousActivityLoop(
            run_agent=_run_autonomous_agent,
            get_vexnet_client=core._get_vexnet_client if core.vexnet_client else None,
            get_moltbook_client=core._get_moltbook_client if core.moltbook_client else None,
            interval_seconds=activity_interval,
            log_dir=os.path.join(core.workspace, ".vex", "activity_logs"),
        )
        activity_loop.start()

    # Connect to VexNet server if enabled
    if core.vexnet_client:
        try:
            await core.vexnet_client.connect()
        except Exception as e:
            renderer.print_error(f"VexNet connection failed: {e}")
            core.vexnet_client = None

    renderer.print_welcome(core.provider, core.model, core.workspace)
    if core.dry_run:
        renderer.print_info("  [DRY RUN mode enabled — no write operations will execute]")
    if core.debug_mode.enabled:
        renderer.print_info("  [DEBUG mode enabled]")
    if core.vexnet_client:
        renderer.print_info("  [VexNet active — use /tools to see net.* tools]")

    tool_call_count = 0

    while True:
        try:
            user_input = await session.prompt_async(
                "> ",
                multiline=False,
            )
        except (EOFError, KeyboardInterrupt):
            renderer.print_info("\nGoodbye.")
            if activity_loop:
                activity_loop.stop()
            if core.vexnet_client:
                await core.vexnet_client.disconnect()
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
                tools = core.tool_registry.list_all()
                for t in tools:
                    renderer.print_info(
                        f"  {t.name} [{t.risk_tier.name}] — {t.description}"
                    )
                continue
            elif cmd == "/agents":
                agents = core.agent_registry.list_all()
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
                        core.agent_def = AgentDefinition(
                            agent_id=core.agent_def.agent_id,
                            display_name=core.agent_def.display_name,
                            system_prompt=core.agent_def.system_prompt,
                            autonomy_level=level,
                            max_tool_rounds=core.agent_def.max_tool_rounds,
                            workspace_root=core.agent_def.workspace_root,
                            dry_run=core.agent_def.dry_run,
                        )
                        core.agent_registry.register(core.agent_def)
                        agent = core.create_agent(
                            approval_callback=approval_manager.check_approval,
                            user_id=user_id,
                            chat_id=user_id,
                            is_dm=True,
                        )
                        renderer.print_info(f"Autonomy level set to {level}.")
                    else:
                        renderer.print_error("Autonomy level must be 0-3.")
                else:
                    renderer.print_info(
                        f"Current autonomy level: {core.agent_def.autonomy_level}"
                    )
                continue
            elif cmd == "/audit":
                entries = core.audit_log.query_recent(10)
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
                state = core.debug_mode.toggle()
                renderer.print_info(f"Debug mode {'enabled' if state else 'disabled'}.")
                continue
            elif cmd == "/dryrun":
                core.agent_def = AgentDefinition(
                    agent_id=core.agent_def.agent_id,
                    display_name=core.agent_def.display_name,
                    system_prompt=core.agent_def.system_prompt,
                    autonomy_level=core.agent_def.autonomy_level,
                    max_tool_rounds=core.agent_def.max_tool_rounds,
                    workspace_root=core.agent_def.workspace_root,
                    dry_run=not core.agent_def.dry_run,
                )
                core.agent_registry.register(core.agent_def)
                agent = core.create_agent(
                    approval_callback=approval_manager.check_approval,
                    user_id=user_id,
                    chat_id=user_id,
                    is_dm=True,
                )
                renderer.print_info(
                    f"Dry-run mode {'enabled' if core.agent_def.dry_run else 'disabled'}."
                )
                continue
            elif cmd == "/metrics":
                stats = core.metrics_collector.get_tool_stats()
                if stats["total"] == 0:
                    renderer.print_info("No metrics collected yet.")
                else:
                    renderer.print_info(
                        f"  Total tool calls: {stats['total']}, "
                        f"success rate: {stats['success_rate']:.0%}, "
                        f"avg duration: {stats['avg_duration_s']:.2f}s"
                    )
                    errors = core.metrics_collector.get_common_errors(5)
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
            elif cmd == "/update":
                renderer.print_info("Checking for updates...")
                from vex.cli.updater import run_update

                success, msg = run_update()
                if success:
                    renderer.print_info(msg)
                    renderer.print_info("Run /restart to apply the update.")
                else:
                    renderer.print_error(msg)
                continue
            elif cmd == "/stop":
                renderer.print_info("Use Ctrl+C to stop a running agent.")
                continue
            elif cmd == "/restart":
                renderer.print_info("Restarting Vex...")
                if activity_loop:
                    activity_loop.stop()
                if core.vexnet_client:
                    await core.vexnet_client.disconnect()
                os.execv(sys.executable, [sys.executable, "-m", "vex.cli.app"])
            elif cmd.startswith("/configure set "):
                parts = user_input.split(maxsplit=3)
                if len(parts) == 4:
                    from vex.config.writer import config_set

                    try:
                        path = config_set(parts[2], parts[3])
                        renderer.print_info(f"Set {parts[2]} = {parts[3]}")
                        renderer.print_info(f"  Config: {path}")
                        renderer.print_info("  Run /restart to apply changes.")
                    except Exception as e:
                        renderer.print_error(f"Failed to set config: {e}")
                else:
                    renderer.print_info("Usage: /configure set <key> <value>")
                continue
            elif cmd.startswith("/configure get "):
                parts = user_input.split(maxsplit=2)
                if len(parts) == 3:
                    from vex.config.writer import config_get

                    val = config_get(parts[2])
                    if val is None:
                        renderer.print_info(f"{parts[2]} is not set")
                    else:
                        renderer.print_info(f"{parts[2]} = {val}")
                else:
                    renderer.print_info("Usage: /configure get <key>")
                continue
            else:
                renderer.print_error(f"Unknown command: {user_input}")
                continue

        # Run agent
        cancel_event = asyncio.Event()

        try:
            renderer.start_streaming()
            console.print()
            tool_call_count = 0

            if core.vexnet_client:
                core.vexnet_client.update_status("in conversation")

            response_text = ""
            async for event in agent.run(user_input, conversation, cancel_event=cancel_event):
                if isinstance(event, StreamEvent):
                    if event.text_delta:
                        renderer.stream_token(event.text_delta)
                        response_text += event.text_delta
                elif isinstance(event, ToolCallEvent):
                    renderer.end_streaming()
                    if event.result is None:
                        renderer.render_tool_call(event)
                    else:
                        renderer.render_tool_result(event)
                        tool_call_count += 1
                    renderer.start_streaming()

            renderer.end_streaming()

            if core.vexnet_client:
                core.vexnet_client.update_status("idle")
            console.print()

            # Async fact extraction (fire-and-forget)
            if response_text.strip():
                asyncio.create_task(
                    core.fact_extractor.extract_and_update(
                        user_id, user_input, response_text
                    )
                )

            # Prompt for feedback after complex operations
            if tool_call_count >= 5:
                rating = await renderer.render_feedback_prompt(session=session)
                if rating:
                    feedback_collector.record(rating, context=user_input[:200])

        except KeyboardInterrupt:
            cancel_event.set()
            renderer.end_streaming()
            renderer.print_info("\n[Stopped]")
        except Exception as e:
            renderer.end_streaming()
            renderer.print_error(str(e))


def _handle_configure(args) -> None:
    """Handle `vex configure` subcommands."""
    from vex.config.writer import config_get, config_set, find_config_path

    if args.configure_action == "set":
        path = config_set(args.key, args.value)
        print(f"  Set {args.key} = {args.value}")
        print(f"  Config: {path}")
    elif args.configure_action == "get":
        val = config_get(args.key)
        if val is None:
            print(f"  {args.key} is not set")
            sys.exit(1)
        else:
            print(f"  {args.key} = {val}")
    elif args.configure_action == "path":
        path = find_config_path()
        print(path or "No config file found")
    else:
        print("Usage: vex configure {set|get|path}")
        sys.exit(1)


def main() -> None:
    """Entry point for the vex CLI.

    Usage:
        vex                                — interactive REPL
        vex --telegram                     — start Telegram bot
        vex configure set <key> <value>    — set a config value
        vex configure get <key>            — get a config value
        vex configure path                 — show config file path
        vex restart                        — restart the REPL (reload config)
    """
    import argparse

    parser = argparse.ArgumentParser(description="Vex — Autonomous AI Agent")
    parser.add_argument(
        "--telegram", action="store_true", help="Start as Telegram bot instead of REPL"
    )
    parser.add_argument("--token", help="Telegram bot token (with --telegram)")
    parser.add_argument("--workspace", help="Workspace directory (default: cwd)")

    subparsers = parser.add_subparsers(dest="command")

    # vex configure set/get/path
    cfg_parser = subparsers.add_parser("configure", help="Read/write config values")
    cfg_sub = cfg_parser.add_subparsers(dest="configure_action")

    set_parser = cfg_sub.add_parser("set", help="Set a config value")
    set_parser.add_argument("key", help="Dotted key (e.g. llm.provider)")
    set_parser.add_argument("value", help="Value to set")

    get_parser = cfg_sub.add_parser("get", help="Get a config value")
    get_parser.add_argument("key", help="Dotted key (e.g. llm.provider)")

    cfg_sub.add_parser("path", help="Show config file path")

    # vex update — pull latest from GitHub
    subparsers.add_parser("update", help="Update Vex to the latest version")

    # vex restart — re-exec the process
    subparsers.add_parser("restart", help="Restart Vex (reload config)")

    args = parser.parse_args()

    if args.command == "configure":
        _handle_configure(args)
        return

    if args.command == "update":
        from vex.cli.updater import run_update

        success, msg = run_update()
        print(msg)
        sys.exit(0 if success else 1)

    if args.command == "restart":
        # Re-exec ourselves to pick up new config
        os.execv(sys.executable, [sys.executable, "-m", "vex.cli.app"])

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
