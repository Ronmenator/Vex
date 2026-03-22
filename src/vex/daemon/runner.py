"""Headless daemon runner — runs whatever is configured (Telegram, VexNet, Moltbook)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler

logger = logging.getLogger("vex.daemon")

PID_FILE = os.path.join(os.path.expanduser("~"), ".vex", "daemon.pid")
LOG_DIR = os.path.join(os.path.expanduser("~"), ".vex", "logs")
DEFAULT_LOG = os.path.join(LOG_DIR, "daemon.log")


def _setup_logging(log_file: str | None = None) -> None:
    """Configure rotating file + stderr logging."""
    log_path = log_file or DEFAULT_LOG
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    # Force UTF-8 on stderr to avoid cp1252 emoji crashes on Windows
    stderr_stream = open(sys.stderr.fileno(), mode="w", encoding="utf-8",
                         closefd=False, errors="replace")
    stderr_handler = logging.StreamHandler(stderr_stream)
    stderr_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)


def _write_pid() -> None:
    """Write current PID to the pid file."""
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid() -> None:
    """Remove the pid file."""
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def _check_existing() -> int | None:
    """Return PID of running daemon, or None."""
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None

    # Check if process is alive
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if handle:
            kernel32.CloseHandle(handle)
            return pid
        return None
    else:
        try:
            os.kill(pid, 0)
            return pid
        except OSError:
            return None


def _has_telegram_token(token: str | None, core: object) -> str | None:
    """Return a Telegram token if one is available, else None."""
    if token:
        return token
    import os as _os

    from_env = _os.environ.get("TELEGRAM_BOT_TOKEN")
    if from_env:
        return from_env
    tg_config = getattr(core, "telegram_config", {})
    tok = tg_config.get("bot_token")
    # After env-var interpolation, empty or still-placeholder means unconfigured
    if tok and not tok.startswith("${"):
        return tok
    return None


async def _run_headless(workspace: str, token: str | None) -> None:
    """Run VexCore + activity loop + VexNet without Telegram."""
    from vex.agent.conversation import Conversation
    from vex.agent.definition import AUTONOMOUS_SYSTEM_PROMPT, AgentDefinition
    from vex.agent.loop import AgentLoop
    from vex.core import VexCore
    from vex.llm.base import StreamEvent

    core = VexCore(workspace=workspace)

    # Non-interactive ask function
    async def _ask(question: str) -> str:
        return "(User was not available to answer: please proceed with your best judgment)"

    core.set_ask_func(_ask)

    # Connect VexNet
    if core.vexnet_client:
        try:
            await core.vexnet_client.connect()
            logger.info("VexNet connected: %s", core.vexnet_client.identity.display_name)
        except Exception as e:
            logger.warning("VexNet connection failed: %s", e)

    # Start activity loop
    activity_loop = None
    if core.vexnet_client or core.moltbook_client:
        from vex.core.activity import AutonomousActivityLoop

        async def _auto_approve(tc, schema) -> bool:
            return True

        bg_def = AgentDefinition(
            agent_id="background",
            display_name="Vex (background)",
            system_prompt=AUTONOMOUS_SYSTEM_PROMPT,
            autonomy_level=3,
            max_tool_rounds=core.agent_def.max_tool_rounds,
            workspace_root=core.workspace,
            dry_run=core.dry_run,
        )
        bg_agent = AgentLoop(
            definition=bg_def,
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

        async def _run_agent(prompt: str) -> str:
            conv = Conversation()
            parts: list[str] = []
            async for event in bg_agent.run(prompt, conv):
                if isinstance(event, StreamEvent) and event.text_delta:
                    parts.append(event.text_delta)
            return "".join(parts)

        activity_interval = core.network_config.get("activity_interval", 300)
        activity_loop = AutonomousActivityLoop(
            run_agent=_run_agent,
            get_vexnet_client=core._get_vexnet_client if core.vexnet_client else None,
            get_moltbook_client=core._get_moltbook_client if core.moltbook_client else None,
            interval_seconds=activity_interval,
            log_dir=os.path.join(core.workspace, ".vex", "activity_logs"),
        )
        activity_loop.start()
        logger.info("Activity loop started (interval=%ds).", activity_interval)
    else:
        logger.warning("No Telegram, VexNet, or Moltbook configured — nothing to run.")
        return

    # Keep the daemon alive
    stop_event = asyncio.Event()

    def _signal_stop() -> None:
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_stop)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    logger.info("Vex daemon running (headless, no Telegram).")
    await stop_event.wait()

    # Cleanup
    if activity_loop:
        activity_loop.stop()
    if core.vexnet_client:
        await core.vexnet_client.disconnect()
    logger.info("Daemon stopped.")


def run_daemon(
    workspace: str | None = None,
    token: str | None = None,
    log_file: str | None = None,
) -> None:
    """Run Vex in headless daemon mode.

    If Telegram is configured, runs the full Telegram bot (which includes
    VexNet + activity loop). Otherwise, runs VexNet + activity loop standalone.
    """
    existing = _check_existing()
    if existing:
        print(f"Vex daemon already running (PID {existing}).", file=sys.stderr)
        sys.exit(1)

    _setup_logging(log_file)
    _write_pid()

    # Graceful shutdown on SIGTERM
    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Received signal %s, shutting down...", signum)
        _remove_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    if sys.platform != "win32":
        signal.signal(signal.SIGHUP, _shutdown)  # type: ignore[attr-defined]

    # Ensure cwd matches workspace so config loader and tools resolve correctly
    ws = workspace or os.getcwd()
    os.chdir(ws)

    logger.info("Starting Vex daemon (PID %d, workspace=%s)...", os.getpid(), ws)

    try:
        # Check if Telegram is available before committing to run_bot
        from vex.core import VexCore

        probe = VexCore(workspace=ws)
        tg_token = _has_telegram_token(token, probe)
        del probe  # free resources, will be re-created by run_bot or _run_headless

        if tg_token:
            logger.info("Telegram token found — starting with Telegram bot.")
            from vex.telegram.bot import run_bot

            run_bot(token=tg_token, workspace=ws)
        else:
            logger.info("No Telegram token — starting headless (VexNet/Moltbook only).")
            asyncio.run(_run_headless(ws, token))

    except KeyboardInterrupt:
        logger.info("Daemon interrupted.")
    except Exception:
        logger.exception("Daemon crashed")
        sys.exit(1)
    finally:
        _remove_pid()
