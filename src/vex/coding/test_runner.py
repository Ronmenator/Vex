"""Test runner — execute tests and parse results."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestFailure:
    """A single test failure."""

    test_name: str
    error_message: str
    file_path: str | None = None
    line_number: int | None = None


@dataclass
class TestResult:
    """Structured result from running tests."""

    passed: bool
    total: int = 0
    failures: int = 0
    output: str = ""
    failure_details: list[TestFailure] = field(default_factory=list)


async def run_tests(
    command: str,
    workspace: str,
    timeout: int = 120,
) -> TestResult:
    """Execute a test command and parse the results.

    Supports pytest output format. Falls back to exit-code-based pass/fail.
    """
    if sys.platform == "win32":
        shell_cmd = ["cmd.exe", "/c", command]
    else:
        shell_cmd = ["/bin/sh", "-c", command]

    try:
        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return TestResult(
                passed=False, output="Test command timed out", failures=1
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        full_output = stdout + ("\n" + stderr if stderr else "")

        return _parse_pytest_output(full_output, process.returncode or 0)

    except OSError as e:
        return TestResult(passed=False, output=str(e), failures=1)


def _parse_pytest_output(output: str, exit_code: int) -> TestResult:
    """Parse pytest output into a structured TestResult."""
    result = TestResult(passed=exit_code == 0, output=output)

    # Try to parse the summary line: "X passed, Y failed, Z errors"
    summary_match = re.search(
        r"(\d+)\s+passed(?:,\s*(\d+)\s+failed)?(?:,\s*(\d+)\s+error)?",
        output,
    )
    if summary_match:
        passed_count = int(summary_match.group(1))
        failed_count = int(summary_match.group(2) or 0)
        error_count = int(summary_match.group(3) or 0)
        result.total = passed_count + failed_count + error_count
        result.failures = failed_count + error_count
    else:
        # Fallback: just use exit code
        result.total = 1
        result.failures = 0 if exit_code == 0 else 1

    # Parse individual failure details
    # Look for "FAILED test_file.py::test_name - ErrorMessage"
    failure_pattern = re.compile(
        r"FAILED\s+([\w/\\._-]+(?:::[\w._-]+)+)\s*-?\s*(.*)"
    )
    for match in failure_pattern.finditer(output):
        test_path = match.group(1)
        error_msg = match.group(2).strip()

        # Split test_path into file and test name
        parts = test_path.split("::")
        file_path = parts[0] if parts else None
        test_name = "::".join(parts[1:]) if len(parts) > 1 else test_path

        result.failure_details.append(
            TestFailure(
                test_name=test_name,
                error_message=error_msg,
                file_path=file_path,
            )
        )

    return result
