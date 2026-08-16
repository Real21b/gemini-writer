"""
Gemini client wrapper: retries, streaming and usage accounting.

This is the only module that talks to the model, so swapping providers or model
versions is a single-file change.
"""

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from google import genai
from google.genai import types

from core.config import RunConfig
from core.prompts import SUMMARY_PROMPT, SYSTEM_PROMPT

# Substrings that mean a request will never succeed on retry.
_PERMANENT_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "unauthorized",
    "permission denied",
    "permission_denied",
    "unauthenticated",
    "invalid_argument",
    "not found",
    "400",
    "401",
    "403",
    "404",
)

# Substrings that mean a transient failure worth retrying.
_TRANSIENT_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "resource_exhausted",
    "rate limit",
    "quota",
    "unavailable",
    "deadline",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "internal error",
    "overloaded",
)


class PermanentAPIError(Exception):
    """Raised when an API call fails in a way that retrying cannot fix."""


def classify_error(exc: BaseException) -> str:
    """Classify an exception as 'permanent' or 'transient'."""
    message = f"{type(exc).__name__}: {exc}".lower()
    for marker in _TRANSIENT_MARKERS:
        if marker in message:
            return "transient"
    for marker in _PERMANENT_MARKERS:
        if marker in message:
            return "permanent"
    # Unknown failures are treated as transient; the attempt limit still applies.
    return "transient"


def call_with_retry(
    func: Callable[[], Any],
    *,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    on_retry: Optional[Callable[[int, float, BaseException], None]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> Any:
    """Call ``func`` with exponential backoff and jitter."""
    last_error: Optional[BaseException] = None
    sleep_fn = sleep if sleep is not None else time.sleep

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            last_error = exc
            if classify_error(exc) == "permanent":
                raise PermanentAPIError(str(exc)) from exc
            if attempt == max_attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= 0.5 + random.random() / 2  # jitter: 50-100% of the delay
            if on_retry:
                on_retry(attempt, delay, exc)
            sleep_fn(delay)

    assert last_error is not None
    raise last_error


def extract_usage(response: Any) -> Dict[str, int]:
    """Read token usage from a Gemini response instead of paying for count_tokens."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {"prompt": 0, "output": 0, "thinking": 0, "total": 0}

    def _int(value: Any) -> int:
        return int(value) if isinstance(value, (int, float)) else 0

    prompt = _int(getattr(usage, "prompt_token_count", 0))
    output = _int(getattr(usage, "candidates_token_count", 0))
    thinking = _int(getattr(usage, "thoughts_token_count", 0))
    total = _int(getattr(usage, "total_token_count", 0)) or (prompt + output + thinking)
    return {"prompt": prompt, "output": output, "thinking": thinking, "total": total}


@dataclass
class TurnResult:
    """One completed model turn."""

    content: Optional[types.Content] = None
    text: str = ""
    thinking: str = ""
    function_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=lambda: {"total": 0})


def _collect_part(part: Any, result: TurnResult) -> Optional[Tuple[str, str]]:
    """Fold one response part into the result, returning a delta to display."""
    if getattr(part, "function_call", None):
        call = part.function_call
        result.function_calls.append(
            {"name": call.name, "args": dict(call.args) if call.args else {}}
        )
        return ("tool", call.name)

    text = getattr(part, "text", None)
    if not text:
        return None

    if getattr(part, "thought", False):
        result.thinking += text
        return ("thinking", text)

    result.text += text
    return ("text", text)


class GeminiLLM:
    """Thin wrapper around google-genai with retries and streaming."""

    def __init__(self, client: genai.Client, config: RunConfig,
                 sleep: Optional[Callable[[float], None]] = None) -> None:
        self.client = client
        self.config = config
        self._sleep = sleep

    # --- configuration -------------------------------------------------------

    def _generate_config(self, tool: Optional[types.Tool]) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            thinking_config=types.ThinkingConfig(thinking_level=self.config.thinking_level),
            tools=[tool] if tool else None,
            temperature=self.config.temperature,
        )

    def _retry(self, func: Callable[[], Any],
               on_retry: Optional[Callable[[int, float, BaseException], None]] = None) -> Any:
        return call_with_retry(
            func,
            max_attempts=self.config.api_max_attempts,
            on_retry=on_retry,
            sleep=self._sleep,
        )

    # --- turns ---------------------------------------------------------------

    def complete_turn(
        self,
        contents: List[types.Content],
        tool: Optional[types.Tool],
        on_retry: Optional[Callable[[int, float, BaseException], None]] = None,
    ) -> TurnResult:
        """Run one non-streaming turn."""
        response = self._retry(
            lambda: self.client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config=self._generate_config(tool),
            ),
            on_retry=on_retry,
        )

        result = TurnResult(usage=extract_usage(response))
        candidates = getattr(response, "candidates", None) or []
        if candidates and candidates[0].content:
            result.content = candidates[0].content
            for part in result.content.parts or []:
                _collect_part(part, result)
        return result

    def stream_turn(
        self,
        contents: List[types.Content],
        tool: Optional[types.Tool],
        on_retry: Optional[Callable[[int, float, BaseException], None]] = None,
    ) -> Iterator[Tuple[str, str]]:
        """
        Run one streaming turn, yielding ('thinking'|'text'|'tool', chunk) deltas.

        The generator's return value is the assembled ``TurnResult``; use
        ``result = yield from llm.stream_turn(...)``.

        Raw parts are accumulated in order, so the model ``Content`` appended to
        the history keeps its thought signatures - dropping those breaks the
        next function call.
        """
        stream = self._retry(
            lambda: self.client.models.generate_content_stream(
                model=self.config.model,
                contents=contents,
                config=self._generate_config(tool),
            ),
            on_retry=on_retry,
        )

        result = TurnResult()
        parts: List[Any] = []

        for chunk in stream:
            usage = extract_usage(chunk)
            if usage["total"]:
                result.usage = usage

            candidates = getattr(chunk, "candidates", None) or []
            if not candidates or not candidates[0].content:
                continue

            for part in candidates[0].content.parts or []:
                parts.append(part)
                delta = _collect_part(part, result)
                if delta:
                    yield delta

        if parts:
            result.content = types.Content(role="model", parts=parts)
        return result

    # --- auxiliary calls -----------------------------------------------------

    def summarize(self, transcript: str) -> str:
        """Summarize a transcript for compression or a recovery snapshot."""
        response = self._retry(
            lambda: self.client.models.generate_content(
                model=self.config.model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=SUMMARY_PROMPT + transcript)],
                    )
                ],
                config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=4096),
            )
        )
        return (getattr(response, "text", "") or "").strip()

    def count_tokens(self, contents: List[types.Content]) -> int:
        """Exact token count. Only used to verify compression, never per iteration."""
        try:
            response = self.client.models.count_tokens(
                model=self.config.model, contents=contents
            )
            return int(response.total_tokens or 0)
        except Exception:  # noqa: BLE001 - fall back to a rough estimate
            chars = sum(
                len(part.text)
                for content in contents
                for part in (content.parts or [])
                if getattr(part, "text", None)
            )
            return chars // 4
