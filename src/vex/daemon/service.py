"""Cross-platform service install/uninstall/start/stop/status."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap

VEX_DIR = os.path.join(os.path.expanduser("~"), ".vex")


def _vex_executable() -> str:
    """Find the vex entry-point script."""
    # Prefer the installed console_script
    vex_bin = shutil.which("vex")
    if vex_bin:
        return vex_bin
    # Fallback: run via python -m
    return f"{sys.executable} -m vex.cli.app"


def _python_executable() -> str:
    """Return the Python that has vex installed."""
    return sys.executable


# ── Linux (systemd user service) ────────────────────────────────────────────

_SYSTEMD_UNIT = "vex.service"
_SYSTEMD_DIR = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
_SYSTEMD_PATH = os.path.join(_SYSTEMD_DIR, _SYSTEMD_UNIT)


def _systemd_unit_content(workspace: str) -> str:
    vex = _vex_executable()
    python = _python_executable()

    # If vex is a script, use it directly; otherwise use python -m
    if os.path.isfile(vex):
        exec_start = f"{vex} daemon run --workspace {workspace}"
    else:
        exec_start = f"{python} -m vex.cli.app daemon run --workspace {workspace}"

    env_file = os.path.join(workspace, ".env")
    env_line = f"EnvironmentFile={env_file}" if os.path.isfile(env_file) else ""

    return textwrap.dedent(f"""\
        [Unit]
        Description=Vex Autonomous AI Agent
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        ExecStart={exec_start}
        Restart=on-failure
        RestartSec=10
        WorkingDirectory={workspace}
        {env_line}

        [Install]
        WantedBy=default.target
    """)


def _systemd_install(workspace: str) -> None:
    os.makedirs(_SYSTEMD_DIR, exist_ok=True)
    content = _systemd_unit_content(workspace)
    with open(_SYSTEMD_PATH, "w") as f:
        f.write(content)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", _SYSTEMD_UNIT], check=True)
    print(f"Installed systemd user service: {_SYSTEMD_PATH}")
    print("Run: vex daemon start")


def _systemd_uninstall() -> None:
    subprocess.run(["systemctl", "--user", "stop", _SYSTEMD_UNIT], check=False)
    subprocess.run(["systemctl", "--user", "disable", _SYSTEMD_UNIT], check=False)
    try:
        os.remove(_SYSTEMD_PATH)
    except FileNotFoundError:
        pass
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print("Vex service uninstalled.")


def _systemd_start() -> None:
    subprocess.run(["systemctl", "--user", "start", _SYSTEMD_UNIT], check=True)
    print("Vex daemon started.")


def _systemd_stop() -> None:
    subprocess.run(["systemctl", "--user", "stop", _SYSTEMD_UNIT], check=True)
    print("Vex daemon stopped.")


def _systemd_status() -> None:
    subprocess.run(["systemctl", "--user", "status", _SYSTEMD_UNIT], check=False)


# ── macOS (launchd) ─────────────────────────────────────────────────────────

_LAUNCHD_LABEL = "ai.vexnet.vex"
_LAUNCHD_DIR = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
_LAUNCHD_PATH = os.path.join(_LAUNCHD_DIR, f"{_LAUNCHD_LABEL}.plist")


def _launchd_plist_content(workspace: str) -> str:
    vex = _vex_executable()
    python = _python_executable()
    log_dir = os.path.join(VEX_DIR, "logs")

    if os.path.isfile(vex):
        args = [vex, "daemon", "run", "--workspace", workspace]
    else:
        args = [python, "-m", "vex.cli.app", "daemon", "run", "--workspace", workspace]

    args_xml = "\n        ".join(f"<string>{a}</string>" for a in args)

    # Propagate key env vars
    env_entries = ""
    for key in ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(key)
        if val:
            env_entries += f"""
        <key>{key}</key>
        <string>{val}</string>"""

    env_block = ""
    if env_entries:
        env_block = f"""
    <key>EnvironmentVariables</key>
    <dict>{env_entries}
    </dict>"""

    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{_LAUNCHD_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
                {args_xml}
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
            <key>StandardOutPath</key>
            <string>{log_dir}/daemon.stdout.log</string>
            <key>StandardErrorPath</key>
            <string>{log_dir}/daemon.stderr.log</string>
            <key>WorkingDirectory</key>
            <string>{workspace}</string>{env_block}
        </dict>
        </plist>
    """)


def _launchd_install(workspace: str) -> None:
    os.makedirs(_LAUNCHD_DIR, exist_ok=True)
    os.makedirs(os.path.join(VEX_DIR, "logs"), exist_ok=True)
    content = _launchd_plist_content(workspace)
    with open(_LAUNCHD_PATH, "w") as f:
        f.write(content)
    print(f"Installed launchd agent: {_LAUNCHD_PATH}")
    print("Run: vex daemon start")


def _launchd_uninstall() -> None:
    subprocess.run(["launchctl", "unload", _LAUNCHD_PATH], check=False)
    try:
        os.remove(_LAUNCHD_PATH)
    except FileNotFoundError:
        pass
    print("Vex service uninstalled.")


def _launchd_start() -> None:
    subprocess.run(["launchctl", "load", _LAUNCHD_PATH], check=True)
    print("Vex daemon started.")


def _launchd_stop() -> None:
    subprocess.run(["launchctl", "unload", _LAUNCHD_PATH], check=True)
    print("Vex daemon stopped.")


def _launchd_status() -> None:
    result = subprocess.run(
        ["launchctl", "list", _LAUNCHD_LABEL],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"Vex daemon is running.\n{result.stdout.strip()}")
    else:
        print("Vex daemon is not running.")


# ── Windows (Scheduled Task, or NSSM if available) ──────────────────────────

_WIN_TASK_NAME = "VexDaemon"
_WIN_NSSM_SERVICE = "Vex"


def _has_nssm() -> bool:
    return shutil.which("nssm") is not None


def _win_install(workspace: str) -> None:
    vex = _vex_executable()
    python = _python_executable()

    if _has_nssm():
        # NSSM: proper Windows service
        if os.path.isfile(vex):
            subprocess.run(
                ["nssm", "install", _WIN_NSSM_SERVICE, vex,
                 "daemon", "run", "--workspace", workspace],
                check=True,
            )
        else:
            subprocess.run(
                ["nssm", "install", _WIN_NSSM_SERVICE, python,
                 "-m", "vex.cli.app", "daemon", "run", "--workspace", workspace],
                check=True,
            )

        # Set log output
        log_dir = os.path.join(VEX_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        subprocess.run(
            ["nssm", "set", _WIN_NSSM_SERVICE, "AppStdout",
             os.path.join(log_dir, "daemon.stdout.log")],
            check=False,
        )
        subprocess.run(
            ["nssm", "set", _WIN_NSSM_SERVICE, "AppStderr",
             os.path.join(log_dir, "daemon.stderr.log")],
            check=False,
        )
        subprocess.run(
            ["nssm", "set", _WIN_NSSM_SERVICE, "AppDirectory", workspace],
            check=False,
        )
        print(f"Installed Windows service '{_WIN_NSSM_SERVICE}' via NSSM.")
        print("Run: vex daemon start")
    else:
        # Fallback: Scheduled Task that runs at logon
        if os.path.isfile(vex):
            task_cmd = f'"{vex}" daemon run --workspace "{workspace}"'
        else:
            task_cmd = f'"{python}" -m vex.cli.app daemon run --workspace "{workspace}"'

        subprocess.run(
            ["schtasks", "/create", "/tn", _WIN_TASK_NAME,
             "/tr", task_cmd, "/sc", "onlogon", "/rl", "highest", "/f"],
            check=True,
        )
        print(f"Installed Windows scheduled task '{_WIN_TASK_NAME}'.")
        print("The daemon will start automatically at next logon.")
        print("To start now: vex daemon start")


def _win_uninstall() -> None:
    if _has_nssm():
        subprocess.run(
            ["nssm", "stop", _WIN_NSSM_SERVICE], check=False
        )
        subprocess.run(
            ["nssm", "remove", _WIN_NSSM_SERVICE, "confirm"], check=False
        )
    else:
        subprocess.run(
            ["schtasks", "/delete", "/tn", _WIN_TASK_NAME, "/f"], check=False
        )
    print("Vex service uninstalled.")


def _win_start() -> None:
    if _has_nssm():
        subprocess.run(["nssm", "start", _WIN_NSSM_SERVICE], check=True)
        print("Vex daemon started.")
    else:
        subprocess.run(["schtasks", "/run", "/tn", _WIN_TASK_NAME], check=True)
        print("Vex daemon started.")


def _win_stop() -> None:
    if _has_nssm():
        subprocess.run(["nssm", "stop", _WIN_NSSM_SERVICE], check=True)
    else:
        # Kill via PID file
        from vex.daemon.runner import _check_existing

        pid = _check_existing()
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=True)
        else:
            print("Vex daemon is not running.")
            return
    print("Vex daemon stopped.")


def _win_status() -> None:
    if _has_nssm():
        result = subprocess.run(
            ["nssm", "status", _WIN_NSSM_SERVICE],
            capture_output=True,
            text=True,
        )
        print(result.stdout.strip() or "Service not found.")
    else:
        from vex.daemon.runner import _check_existing

        pid = _check_existing()
        if pid:
            print(f"Vex daemon is running (PID {pid}).")
        else:
            print("Vex daemon is not running.")


# ── Dispatcher ───────────────────────────────────────────────────────────────

def _platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    else:
        return "linux"


def install(workspace: str | None = None) -> None:
    ws = workspace or os.getcwd()
    p = _platform()
    if p == "linux":
        _systemd_install(ws)
    elif p == "macos":
        _launchd_install(ws)
    elif p == "windows":
        _win_install(ws)


def uninstall() -> None:
    p = _platform()
    if p == "linux":
        _systemd_uninstall()
    elif p == "macos":
        _launchd_uninstall()
    elif p == "windows":
        _win_uninstall()


def start() -> None:
    p = _platform()
    if p == "linux":
        _systemd_start()
    elif p == "macos":
        _launchd_start()
    elif p == "windows":
        _win_start()


def stop() -> None:
    p = _platform()
    if p == "linux":
        _systemd_stop()
    elif p == "macos":
        _launchd_stop()
    elif p == "windows":
        _win_stop()


def status() -> None:
    p = _platform()
    if p == "linux":
        _systemd_status()
    elif p == "macos":
        _launchd_status()
    elif p == "windows":
        _win_status()
