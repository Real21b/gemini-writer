"""
Context management.

The old implementation flattened the entire history to plain text whenever it
compressed, which destroyed function calls, function responses and thought
signatures - the run could break right after a compression (B-05).

This version keeps the recent turns as raw ``Content`` objects and only
summarizes the older prefix, always cutting on a turn boundary so a model's
function call is never separated from its response.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from google.genai import types

from core.llm import GeminiLLM
from core.workspace import Workspace

MAX_ARG_CHARS = 120
MAX_RESULT_CHARS = 300
MAX_THINKING_CHARS = 500
MIN_CONTENTS_TO_SUMMARIZE = 2

SUMMARY_HEADER = "[CONTEXT SUMMARY - earlier turns were compressed]"
SUMMARY_FOOTER = "[END CONTEXT SUMMARY - continue from here]"


def _truncate(text: Any, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "..."


def render_part(part: Any) -> Optional[str]:
    """Render one part as text for a summarizer or a snapshot."""
    call = getattr(part, "function_call", None)
    if call:
        args = getattr(call, "args", None) or {}
        rendered = ", ".join(f"{k}={_truncate(v, MAX_ARG_CHARS)}" for k, v in args.items())
        return f"[Tool call] {call.name}({rendered})"

    response = getattr(part, "function_response", None)
    if response:
        payload = getattr(response, "response", None) or {}
        result = payload.get("result", payload) if isinstance(payload, dict) else payload
        return f"[Tool result] {response.name}: {_truncate(result, MAX_RESULT_CHARS)}"

    text = getattr(part, "text", None)
    if not text:
        return None
    if getattr(part, "thought", False):
        return f"[Thinking] {_truncate(text, MAX_THINKING_CHARS)}"
    return text


def render_contents(contents: List[types.Content]) -> str:
    """
    Render a history as a transcript.

    Tool calls and results are included: a summary that omits them cannot answer
    "which chapters are already written?", which is the whole point of a
    recovery snapshot.
    """
    lines: List[str] = []
    for content in contents:
        rendered = [piece for piece in (render_part(p) for p in content.parts or []) if piece]
        if not rendered:
            continue
        speaker = "Assistant" if content.role == "model" else "User"
        lines.append(f"[{speaker}]\n" + "\n".join(rendered))
    return "\n\n".join(lines)


def is_boundary(contents: List[types.Content], index: int) -> bool:
    """
    True when the history can be cut just before ``index``.

    A model turn containing a function call must stay attached to the user turn
    carrying its function responses, so a cut is only valid before a model turn
    or before a genuine (non tool-result) user message.
    """
    if index <= 0 or index >= len(contents):
        return False

    content = contents[index]
    if content.role == "model":
        return True
    return not any(getattr(part, "function_response", None) for part in content.parts or [])


def find_cut_point(contents: List[types.Content], desired: int) -> int:
    """Snap ``desired`` to the nearest valid boundary at or before it."""
    for index in range(min(desired, len(contents) - 1), 0, -1):
        if is_boundary(contents, index):
            return index
    return 0


@dataclass
class CompressionResult:
    compressed: bool
    contents_before: int = 0
    contents_after: int = 0
    summary_chars: int = 0
    reason: str = ""


class ContextManager:
    """Owns the conversation history for one run."""

    def __init__(self, llm: GeminiLLM, workspace: Workspace, keep_recent: int = 12) -> None:
        self.llm = llm
        self.workspace = workspace
        self.keep_recent = keep_recent
        self.contents: List[types.Content] = []
        self.original_request: str = ""

    # --- building the history ------------------------------------------------

    def add_user_text(self, text: str) -> None:
        if not self.original_request:
            self.original_request = text
        self.contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=text)])
        )

    def add_model_content(self, content: types.Content) -> None:
        """Append the model turn verbatim - thought signatures must survive."""
        self.contents.append(content)

    def add_tool_results(self, parts: List[types.Part]) -> None:
        self.contents.append(types.Content(role="user", parts=parts))

    def __len__(self) -> int:
        return len(self.contents)

    # --- compression ---------------------------------------------------------

    def compress(self) -> CompressionResult:
        """Summarize the older prefix, keeping recent turns intact."""
        before = len(self.contents)
        if before <= MIN_CONTENTS_TO_SUMMARIZE:
            return CompressionResult(False, before, before, reason="history too short")

        cut = find_cut_point(self.contents, max(1, before - self.keep_recent))
        if cut <= 0:
            return CompressionResult(False, before, before, reason="no safe cut point")

        head, tail = self.contents[:cut], self.contents[cut:]
        summary = (self.llm.summarize(render_contents(head)) or "").strip()
        if not summary:
            return CompressionResult(False, before, before, reason="empty summary")

        self.contents = [self._summary_content(summary)] + tail
        return CompressionResult(
            True,
            contents_before=before,
            contents_after=len(self.contents),
            summary_chars=len(summary),
        )

    def _summary_content(self, summary: str) -> types.Content:
        """
        The durable core that survives every compression: the original request,
        the summary, and the story bible.
        """
        from core.tools.bible import bible_digest  # local import: avoids a cycle

        blocks = [SUMMARY_HEADER]
        if self.original_request:
            blocks.append(f"[ORIGINAL REQUEST]\n{self.original_request}")
        blocks.append(summary)

        digest = bible_digest(self.workspace)
        if digest:
            blocks.append(f"[STORY BIBLE - current]\n{digest}")

        files = self._file_inventory()
        if files:
            blocks.append(f"[FILES ON DISK]\n{files}")

        blocks.append(SUMMARY_FOOTER)
        return types.Content(
            role="user", parts=[types.Part.from_text(text="\n\n".join(blocks))]
        )

    def _file_inventory(self) -> str:
        if not self.workspace.is_ready:
            return ""
        try:
            return "\n".join(info.as_line() for info in self.workspace.list_files())
        except OSError:
            return ""

    # --- snapshots -----------------------------------------------------------

    def snapshot(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Write a recovery snapshot of the whole conversation.

        Returns (path, meta) or None when there is nothing worth saving.
        """
        if len(self.contents) < MIN_CONTENTS_TO_SUMMARIZE:
            return None

        summary = (self.llm.summarize(render_contents(self.contents)) or "").strip()
        if not summary:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.workspace.snapshot_path(timestamp)

        body = [
            "# Context Summary",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Turns summarized:** {len(self.contents)}",
        ]
        if self.original_request:
            body.append(f"**Original request:** {self.original_request}")
        body.append("---")
        body.append(summary)

        inventory = self._file_inventory()
        if inventory:
            body.append("## Files on disk\n\n" + inventory)

        path.write_text("\n\n".join(body) + "\n", encoding="utf-8")
        return str(path), {"turns": len(self.contents), "summary_chars": len(summary)}
