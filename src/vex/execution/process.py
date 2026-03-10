"""Process manager — isolation, tracking, and cancellation."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class ProcessInfo:
    """Tracks a running process."""

    pid: int
    command: str
    process: asyncio.subprocess.Process
    started_at: float


class ProcessManager:
    """Manages running processes with tracking and cancellation."""

    def __init__(self) -> None:
        self._processes: dict[int, ProcessInfo] = {}

    async def run_streaming(
        self,
        command: str,
        cwd: str,
        timeout: int = 60,
    ) -> AsyncIterator[tuple[str, str]]:
        """Run a command and yield (stream, data) tuples as output arrives.

        stream is 'stdout', 'stderr', or 'exit'.
        """
        if sys.platform == "win32":
            shell_cmd = ["cmd.exe", "/c", command]
        else:
            shell_cmd = ["/bin/sh", "-c", command]

        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        import time

        info = ProcessInfo(
            pid=process.pid or 0,
            command=command,
            process=process,
            started_at=time.monotonic(),
        )
        self._processes[info.pid] = info

        try:
            async def read_stream(
                stream: asyncio.StreamReader | None, name: str
            ) -> AsyncIterator[tuple[str, str]]:
                if stream is None:
                    return
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    yield (name, line.decode("utf-8", errors="replace"))

            # Read stdout and stderr concurrently
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )

                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")

                for line in stdout.splitlines(keepends=True):
                    yield ("stdout", line)

                for line in stderr.splitlines(keepends=True):
                    yield ("stderr", line)

            except asyncio.TimeoutError:
                self.kill(info.pid)
                await process.wait()
                yield ("stderr", f"\n[Process timed out after {timeout}s]\n")

            yield ("exit", str(process.returncode or -1))

        finally:
            self._processes.pop(info.pid, None)

    def kill(self, pid: int) -> bool:
        """Kill a tracked process."""
        info = self._processes.get(pid)
        if not info:
            return False

        try:
            info.process.kill()
            return True
        except (OSError, ProcessLookupError):
            return False

    def list_running(self) -> list[ProcessInfo]:
        """List all tracked running processes."""
        return list(self._processes.values())

    def kill_all(self) -> int:
        """Kill all tracked processes. Returns count killed."""
        count = 0
        for pid in list(self._processes.keys()):
            if self.kill(pid):
                count += 1
        return count
