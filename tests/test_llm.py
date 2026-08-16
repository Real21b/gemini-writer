"""LLM wrapper: retries, error classification, usage and streaming assembly."""

from types import SimpleNamespace

import pytest
from google.genai import types

from core.config import RunConfig
from core.llm import (
    GeminiLLM,
    PermanentAPIError,
    call_with_retry,
    classify_error,
    extract_usage,
)


def noop_sleep(_seconds):
    return None


# --- retries (B-06) ---------------------------------------------------------


def test_succeeds_without_retry():
    calls = []
    assert call_with_retry(lambda: calls.append(1) or "ok", sleep=noop_sleep) == "ok"
    assert len(calls) == 1


def test_retries_transient_errors_then_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("503 service unavailable")
        return "ok"

    assert call_with_retry(fn, sleep=noop_sleep) == "ok"
    assert len(calls) == 3


def test_gives_up_after_max_attempts():
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError("429 rate limit exceeded")

    with pytest.raises(RuntimeError):
        call_with_retry(fn, max_attempts=3, sleep=noop_sleep)
    assert len(calls) == 3


def test_permanent_error_is_not_retried():
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError("400 API key not valid")

    with pytest.raises(PermanentAPIError):
        call_with_retry(fn, sleep=noop_sleep)
    assert len(calls) == 1


def test_backoff_grows_and_stays_bounded():
    delays = []

    def fn():
        raise RuntimeError("503 unavailable")

    with pytest.raises(RuntimeError):
        call_with_retry(fn, max_attempts=5, base_delay=2.0, max_delay=10.0, sleep=delays.append)

    assert len(delays) == 4
    assert all(0 < d <= 10.0 for d in delays)
    assert delays[0] < delays[-1]


def test_keyboard_interrupt_propagates():
    def fn():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        call_with_retry(fn, sleep=noop_sleep)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("429 Too Many Requests", "transient"),
        ("503 Service Unavailable", "transient"),
        ("Connection reset by peer", "transient"),
        ("API key not valid", "permanent"),
        ("403 permission denied", "permanent"),
        ("something nobody has seen before", "transient"),
    ],
)
def test_classify_error(message, expected):
    assert classify_error(RuntimeError(message)) == expected


# --- usage (B-07) -----------------------------------------------------------


def test_extract_usage_reads_response_metadata():
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=50,
            thoughts_token_count=25,
            total_token_count=175,
        )
    )
    assert extract_usage(response) == {"prompt": 100, "output": 50, "thinking": 25, "total": 175}


def test_extract_usage_computes_a_missing_total():
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=5,
            thoughts_token_count=2,
            total_token_count=None,
        )
    )
    assert extract_usage(response)["total"] == 17


def test_extract_usage_without_metadata():
    assert extract_usage(SimpleNamespace())["total"] == 0


# --- streaming --------------------------------------------------------------


def chunk(parts, total=None):
    usage = (
        SimpleNamespace(
            prompt_token_count=total, candidates_token_count=0,
            thoughts_token_count=0, total_token_count=total,
        )
        if total
        else None
    )
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
        usage_metadata=usage,
    )


class StreamingModels:
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.attempts = 0

    def generate_content_stream(self, model, contents, config=None):
        self.attempts += 1
        if self.error and self.attempts == 1:
            raise self.error
        return iter(self.chunks)

    def generate_content(self, model, contents, config=None):
        self.attempts += 1
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(content=types.Content(role="model", parts=self.chunks[0]))
            ],
            usage_metadata=SimpleNamespace(
                prompt_token_count=1, candidates_token_count=1,
                thoughts_token_count=0, total_token_count=2,
            ),
        )


class StreamingClient:
    def __init__(self, chunks, error=None):
        self.models = StreamingModels(chunks, error)


def drain(generator):
    """Consume a generator, returning (yields, return_value)."""
    yields = []
    while True:
        try:
            yields.append(next(generator))
        except StopIteration as stop:
            return yields, stop.value


def test_stream_turn_yields_deltas_and_assembles_the_content():
    chunks = [
        chunk([types.Part(text="thinking about it", thought=True)]),
        chunk([types.Part.from_text(text="Once upon ")]),
        chunk([types.Part.from_text(text="a time")]),
        chunk(
            [types.Part(function_call=types.FunctionCall(name="write_file", args={"filename": "a.md"}))],
            total=1234,
        ),
    ]
    llm = GeminiLLM(StreamingClient(chunks), RunConfig(), sleep=noop_sleep)

    deltas, result = drain(llm.stream_turn([], None))

    assert deltas == [
        ("thinking", "thinking about it"),
        ("text", "Once upon "),
        ("text", "a time"),
        ("tool", "write_file"),
    ]
    assert result.text == "Once upon a time"
    assert result.thinking == "thinking about it"
    assert result.function_calls == [{"name": "write_file", "args": {"filename": "a.md"}}]
    assert result.usage["total"] == 1234
    # every raw part is preserved, in order, so thought signatures survive
    assert len(result.content.parts) == 4


def test_stream_turn_retries_a_failed_start():
    chunks = [chunk([types.Part.from_text(text="ok")], total=5)]
    client = StreamingClient(chunks, error=RuntimeError("503 unavailable"))
    llm = GeminiLLM(client, RunConfig(), sleep=noop_sleep)

    _, result = drain(llm.stream_turn([], None))

    assert client.models.attempts == 2
    assert result.text == "ok"


def test_complete_turn_is_used_when_streaming_is_off():
    parts = [types.Part(function_call=types.FunctionCall(name="finish_task", args={"summary": "s"}))]
    llm = GeminiLLM(StreamingClient([parts]), RunConfig(stream=False), sleep=noop_sleep)

    result = llm.complete_turn([], None)

    assert result.function_calls[0]["name"] == "finish_task"
    assert result.usage["total"] == 2


def test_count_tokens_falls_back_to_an_estimate():
    class NoCount:
        models = SimpleNamespace(
            count_tokens=lambda **_: (_ for _ in ()).throw(RuntimeError("nope"))
        )

    llm = GeminiLLM(NoCount(), RunConfig(), sleep=noop_sleep)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text="x" * 400)])]

    assert llm.count_tokens(contents) == 100
