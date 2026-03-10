"""CLI renderer — streaming output, tool call display, formatting."""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from vex.agent.loop import ToolCallEvent
from vex.llm.base import StreamEvent
from vex.tools.base import RiskTier


# Risk tier colors and labels
RISK_COLORS = {
    RiskTier.READ_ONLY: "green",
    RiskTier.WRITE_LOCAL: "yellow",
    RiskTier.WRITE_EXTERNAL: "bright_magenta",
    RiskTier.DESTRUCTIVE: "red",
}

RISK_LABELS = {
    RiskTier.READ_ONLY: "read",
    RiskTier.WRITE_LOCAL: "write",
    RiskTier.WRITE_EXTERNAL: "external",
    RiskTier.DESTRUCTIVE: "destructive",
}


class Renderer:
    """Handles all terminal output for the Vex CLI."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._stream_buffer = ""

    def print_welcome(self, provider: str, model: str, workspace: str) -> None:
        self.console.print()
        title = Text("Vex", style="bold bright_cyan")
        title.append(" v0.1", style="dim")
        title.append(" | ", style="dim")
        title.append(model, style="bright_white")
        title.append(" | ", style="dim")
        title.append(workspace, style="dim")
        self.console.print(title)
        self.console.print(
            Text("Type your message. /quit to exit, /clear to reset.", style="dim")
        )
        self.console.print()

    def start_streaming(self) -> None:
        """Reset the stream buffer for a new response."""
        self._stream_buffer = ""

    def stream_token(self, token: str) -> None:
        """Print a single token to the terminal (streaming)."""
        self.console.print(token, end="", highlight=False)
        self._stream_buffer += token

    def end_streaming(self) -> None:
        """Finalize streaming output."""
        if self._stream_buffer:
            self.console.print()  # Final newline
        self._stream_buffer = ""

    def render_tool_call(self, event: ToolCallEvent) -> None:
        """Render a tool call with its schema info."""
        tc = event.tool_call
        schema = event.schema
        risk = schema.risk_tier if schema else RiskTier.DESTRUCTIVE
        color = RISK_COLORS.get(risk, "red")
        label = RISK_LABELS.get(risk, "unknown")

        # Tool name + risk badge
        header = Text()
        header.append("  tool: ", style="dim")
        header.append(tc.name, style=f"bold {color}")
        header.append(f" [{label}]", style=color)
        self.console.print(header)

        # Truncated arguments
        args_preview = _truncate_args(tc.arguments)
        if args_preview:
            self.console.print(f"  {' ' * 4}{args_preview}", style="dim")

    def render_tool_result(self, event: ToolCallEvent) -> None:
        """Render the result of a tool execution."""
        result = event.result
        if result is None:
            return

        if result.is_error:
            self.console.print(f"  {' ' * 4}error: {result.error}", style="red")
        else:
            output = result.output or "OK"
            # Show truncated output
            lines = output.splitlines()
            if len(lines) > 5:
                preview = "\n".join(lines[:5]) + f"\n... ({len(lines)} lines total)"
            elif len(output) > 300:
                preview = output[:300] + "..."
            else:
                preview = output
            self.console.print(f"  {' ' * 4}done ({len(output)} chars)", style="green")

    def render_approval_prompt(self, event: ToolCallEvent) -> str:
        """Show an approval prompt and return the user's choice."""
        self.console.print(
            f"  {' ' * 4}This action requires approval.",
            style="bright_yellow",
        )
        response = self.console.input(
            Text("  " + " " * 4 + "Allow? [y/n/always]: ", style="bright_yellow")
        ).strip().lower()
        return response

    def render_progress(self, current: int, total: int, label: str = "") -> None:
        """Render a progress indicator."""
        bar_width = 20
        filled = int(bar_width * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_width - filled)
        pct = int(100 * current / total) if total > 0 else 0
        text = Text()
        text.append(f"  [{bar}] {pct}%", style="bright_cyan")
        if label:
            text.append(f" {label}", style="dim")
        self.console.print(text)

    def render_summary(self, summary: str) -> None:
        """Render a summary of completed operations."""
        self.console.print()
        self.console.print(f"  {summary}", style="bold dim")

    def render_feedback_prompt(self) -> str | None:
        """Ask for quick feedback after a long operation."""
        try:
            response = self.console.input(
                Text("  Was this helpful? [y/n/skip]: ", style="dim")
            ).strip().lower()
            if response in ("y", "n"):
                return "positive" if response == "y" else "negative"
        except (EOFError, KeyboardInterrupt):
            pass
        return None

    def print_error(self, message: str) -> None:
        self.console.print(f"Error: {message}", style="red")

    def print_info(self, message: str) -> None:
        self.console.print(message, style="dim")


def _truncate_args(args: dict, max_len: int = 120) -> str:
    """Create a truncated preview of tool arguments."""
    parts = []
    for key, value in args.items():
        val_str = str(value)
        if len(val_str) > 50:
            val_str = val_str[:50] + "..."
        parts.append(f"{key}={val_str!r}")

    result = ", ".join(parts)
    if len(result) > max_len:
        result = result[:max_len] + "..."
    return result
