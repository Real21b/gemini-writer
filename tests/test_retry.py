"""Retry, error classification and token accounting (B-06, B-07)."""

from types import SimpleNamespace

import pytest

from utils import (
    PermanentAPIError,
    call_with_retry,
    classify_error,
    extract_usage,
)


def noop_sleep(_seconds):
    return None


def test_succeeds_without_retry():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    assert call_with_retry(fn, sleep=noop_sleep) == "ok"
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
        call_with_retry(
            fn,
            max_attempts=5,
            base_delay=2.0,
            max_delay=10.0,
            sleep=delays.append,
        )

    assert len(delays) == 4
    assert all(0 < d <= 10.0 for d in delays)
    assert delays[0] < delays[-1]  # exponential growth survives the jitter


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
        ("Deadline exceeded", "transient"),
        ("API key not valid", "permanent"),
        ("403 permission denied", "permanent"),
        ("something nobody has seen before", "transient"),
    ],
)
def test_classify_error(message, expected):
    assert classify_error(RuntimeError(message)) == expected


def test_extract_usage_reads_response_metadata():
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=50,
            thoughts_token_count=25,
            total_token_count=175,
        )
    )
    assert extract_usage(response) == {
        "prompt": 100,
        "output": 50,
        "thinking": 25,
        "total": 175,
    }


def test_extract_usage_computes_total_when_missing():
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
