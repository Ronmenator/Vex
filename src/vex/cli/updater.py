"""Self-update: pip install --upgrade from GitHub."""

from __future__ import annotations

import subprocess
import sys

REPO_URL = "git+https://github.com/ronmenator/vex.git"


def run_update() -> tuple[bool, str]:
    """Pull the latest version from GitHub.

    Returns (success, message).
    """
    try:
        old_version = _current_version()

        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", REPO_URL],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return False, f"Update failed: {stderr or result.stdout.strip()}"

        new_version = _current_version(fresh=True)

        if new_version != old_version:
            return True, f"Updated vex {old_version} → {new_version}"
        else:
            return True, f"Already up to date (v{new_version})."

    except subprocess.TimeoutExpired:
        return False, "Update timed out — check your network connection."
    except Exception as e:
        return False, f"Update failed: {e}"


def _current_version(fresh: bool = False) -> str:
    """Return the installed vex version."""
    if fresh:
        # Re-read from metadata to pick up the just-installed version
        try:
            from importlib.metadata import version

            return version("vexnet")
        except Exception:
            pass
    try:
        from vex import __version__

        return __version__
    except Exception:
        return "unknown"
