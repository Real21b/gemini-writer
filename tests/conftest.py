"""Shared fixtures: a workspace on tmp_path and a scriptable fake LLM."""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
from google.genai import types

from core.config import RunConfig
from core.llm import TurnResult
from core.workspace import Workspace


# --- building model turns ---------------------------------------------------


def turn(
    text: str = "",
    calls: Sequence[Tuple[str, Dict[str, Any]]] = (),
    thinking: str = "",
    tokens: int = 1_000,
) -> TurnResult:
    """Build a TurnResult the way the real LLM wrapper would assemble one."""
    parts: List[types.Part] = []
    if thinking:
        parts.append(types.Part(text=thinking, thought=True))
    if text:
        parts.append(types.Part.from_text(text=text))
    for name, args in calls:
        parts.append(types.Part(function_call=types.FunctionCall(name=name, args=args)))

    return TurnResult(
        content=types.Content(role="model", parts=parts),
        text=text,
        thinking=thinking,
        function_calls=[{"name": name, "args": dict(args)} for name, args in calls],
        usage={"prompt": tokens // 2, "output": tokens // 2, "thinking": 0, "total": tokens},
    )


class FakeLLM:
    """Replays scripted turns; records the history it was called with."""

    def __init__(self, turns: Iterable[Any] = (), summary: str = "SUMMARY", token_count: int = 500):
        self.turns = list(turns)
        self.summary_text = summary
        self.token_count = token_count
        self.calls: List[List[types.Content]] = []
        self.summaries: List[str] = []
        self.count_token_calls = 0

    def _next(self, contents) -> TurnResult:
        self.calls.append(list(contents))
        if not self.turns:
            raise AssertionError("The runner asked for more turns than the script provides")
        item = self.turns.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def stream_turn(self, contents, tool, on_retry=None):
        result = self._next(contents)
        if result.thinking:
            yield ("thinking", result.thinking)
        if result.text:
            yield ("text", result.text)
        for call in result.function_calls:
            yield ("tool", call["name"])
        return result

    def complete_turn(self, contents, tool, on_retry=None) -> TurnResult:
        return self._next(contents)

    def summarize(self, transcript: str) -> str:
        self.summaries.append(transcript)
        return self.summary_text

    def count_tokens(self, contents) -> int:
        self.count_token_calls += 1
        return self.token_count


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def output_root(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    return root


@pytest.fixture
def workspace(output_root) -> Workspace:
    """A workspace with an active project folder."""
    ws = Workspace(output_root=output_root)
    ws.create_project("test_project")
    return ws


@pytest.fixture
def empty_workspace(output_root) -> Workspace:
    """A workspace with no project created yet."""
    return Workspace(output_root=output_root)


@pytest.fixture
def config() -> RunConfig:
    return RunConfig(max_iterations=10, backup_interval=0, stream=True)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


def make_llm(turns: Optional[Iterable[Any]] = None, **kwargs) -> FakeLLM:
    return FakeLLM(turns or [], **kwargs)
