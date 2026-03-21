"""Headless daemon runner — Telegram bot + activity loop without a REPL."""

from __future__ import annotations

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
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(fmt)

    stderr_handler = logging.StreamHandler(sys.stderr)
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


def run_daemon(
    workspace: str | None = None,
    token: str | None = None,
    log_file: str | None = None,
) -> None:
    """Run Vex in headless daemon mode (Telegram bot + activity loop)."""
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

    logger.info("Starting Vex daemon (PID %d)...", os.getpid())

    try:
        from vex.telegram.bot import run_bot

        run_bot(token=token, workspace=workspace)
    except KeyboardInterrupt:
        logger.info("Daemon interrupted.")
    except Exception:
        logger.exception("Daemon crashed")
        sys.exit(1)
    finally:
        _remove_pid()
