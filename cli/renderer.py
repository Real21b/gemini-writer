"""
Terminal renderer for the event stream.

The renderer holds all presentation logic; the runner knows nothing about it.
Swapping this file for an SSE writer is what phase 2 does.
"""

import sys
from typing import Optional, TextIO

from core.events import Event, EventType

LINE = "─" * 60
RULE = "=" * 60


class ConsoleRenderer:
    """Prints events as they arrive, streaming deltas inline."""

    def __init__(self, stream: Optional[TextIO] = None, verbose: bool = False) -> None:
        # Resolved on every write: binding sys.stdout at construction time breaks
        # redirection (and hides output from test capture).
        self._stream = stream
        self.verbose = verbose
        self._inline: Optional[str] = None  # which delta block is open
        self.snapshot_path: Optional[str] = None

    # --- helpers -------------------------------------------------------------

    @property
    def stream(self) -> TextIO:
        return self._stream if self._stream is not None else sys.stdout

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _close_inline(self) -> None:
        if self._inline:
            self._write("\n")
            self._inline = None

    def _line(self, text: str = "") -> None:
        self._close_inline()
        self._write(text + "\n")

    def _delta(self, kind: str, marker: str, text: str) -> None:
        if self._inline != kind:
            self._close_inline()
            self._write(marker)
            self._inline = kind
        self._write(text)

    # --- event dispatch ------------------------------------------------------

    def handle(self, event: Event) -> None:
        handler = getattr(self, f"_on_{event.type.name.lower()}", None)
        if handler:
            handler(event.data)
        elif self.verbose:
            self._line(f"· {event.type.value} {event.data}")

    def _on_run_started(self, data: dict) -> None:
        self._line(RULE)
        self._line("Gemini Writing Agent")
        self._line(RULE)
        if data.get("recovery"):
            self._line("🔄 Recovery mode: continuing from a saved snapshot")
        else:
            self._line(f"📝 Task: {data['prompt']}")
        self._line(f"Model: {data['model']}   Max iterations: {data['max_iterations']}")
        self._line(f"Tools: {', '.join(data.get('tools', []))}")
        self._line(RULE)

    def _on_iteration_started(self, data: dict) -> None:
        self._line()
        self._line(LINE)
        header = f"Iteration {data['iteration']}/{data['max_iterations']}"
        if data.get("tokens"):
            header += f"   ·   {data['tokens']:,} tokens"
        self._line(header)
        self._line(LINE)

    def _on_thinking_delta(self, data: dict) -> None:
        self._delta("thinking", "🧠 ", data["text"])

    def _on_text_delta(self, data: dict) -> None:
        self._delta("text", "💬 ", data["text"])

    def _on_tool_call(self, data: dict) -> None:
        self._close_inline()
        args = ", ".join(f"{k}={v}" for k, v in data.get("args", {}).items())
        self._line(f"🔧 {data['name']}({args})")

    def _on_tool_result(self, data: dict) -> None:
        icon = "✓" if data.get("ok") else "✗"
        result = data.get("result", "")
        first_line = result.splitlines()[0] if result else ""
        self._line(f"   {icon} {first_line[:200]}")

    def _on_file_written(self, data: dict) -> None:
        self._line(f"   📄 {data['path']} — {data.get('words', 0):,} words ({data['mode']})")

    def _on_usage_updated(self, data: dict) -> None:
        if self.verbose:
            self._line(
                f"📊 tokens: {data.get('total', 0):,} "
                f"(prompt {data.get('prompt', 0):,}, output {data.get('output', 0):,}, "
                f"thinking {data.get('thinking', 0):,})"
            )

    def _on_context_compressed(self, data: dict) -> None:
        self._line(
            f"🗜️  Context compressed: {data['turns_before']} → {data['turns_after']} turns, "
            f"{data['tokens_before']:,} → {data['tokens_after']:,} tokens"
        )

    def _on_snapshot_saved(self, data: dict) -> None:
        self.snapshot_path = data["path"]
        self._line(f"💾 Snapshot saved ({data['reason']}): {data['path']}")

    def _on_warning(self, data: dict) -> None:
        self._line(f"⚠️  {data.get('message', '')}")

    def _on_run_completed(self, data: dict) -> None:
        self._line()
        self._line(RULE)
        self._line("✅ TASK COMPLETED")
        self._line(RULE)
        self._line(data.get("summary", ""))
        files = data.get("files") or []
        if files:
            self._line(f"\nFiles ({len(files)}):")
            for path in files:
                self._line(f"  · {path}")
        self._line(
            f"\n{data.get('total_words', 0):,} words · {data['iteration']} iteration(s) · "
            f"{data.get('tokens', 0):,} tokens"
        )
        self._line(RULE)

    def _on_run_failed(self, data: dict) -> None:
        self._line()
        self._line(RULE)
        self._line(f"✗ RUN FAILED ({data['error_type']})")
        self._line(RULE)
        self._line(data.get("message", ""))
        self.print_recovery_hint()

    def _on_run_needs_input(self, data: dict) -> None:
        self._line()
        self._line(RULE)
        self._line("❓ THE AGENT NEEDS YOUR INPUT")
        self._line(RULE)
        self._line(data.get("question", ""))
        self.print_recovery_hint()

    # --- helpers used by the CLI --------------------------------------------

    def print_recovery_hint(self) -> None:
        if self.snapshot_path:
            self._line("\nTo resume, run:")
            self._line(f"  python writer.py --recover {self.snapshot_path}")


def render_event(event: Event, renderer: ConsoleRenderer) -> None:
    renderer.handle(event)


TERMINAL = {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_NEEDS_INPUT}
