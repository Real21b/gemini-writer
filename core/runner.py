"""
The agent loop.

``AgentRunner.run()`` is a generator of :class:`core.events.Event`. It never
prints and never reads the environment, which is what lets the same loop back a
terminal renderer today and an SSE endpoint later.
"""

from typing import Any, Dict, Iterator, List, Optional

from google.genai import types

from core.config import RunConfig
from core.context import ContextManager
from core.events import Event, EventEmitter, EventType
from core.llm import GeminiLLM, PermanentAPIError, TurnResult
from core.prompts import CONTINUE_NUDGE
from core.tools import REGISTRY, ToolContext, ToolRegistry
from core.workspace import Workspace

RECOVERY_PREFIX = (
    "[RECOVERED CONTEXT]\n\n{context}\n\n[END RECOVERED CONTEXT]\n\n"
    "Continue the work from where it left off. Check list_files first, compare it with the "
    "plan, and carry on with the next unwritten piece."
)


class AgentRunner:
    """Runs one writing task to completion."""

    def __init__(
        self,
        llm: GeminiLLM,
        workspace: Workspace,
        config: RunConfig,
        registry: ToolRegistry = REGISTRY,
    ) -> None:
        self.llm = llm
        self.workspace = workspace
        self.config = config
        self.registry = registry
        self.events = EventEmitter()
        self.context = ContextManager(llm, workspace, keep_recent=config.keep_recent_contents)
        self.tool_ctx = ToolContext(workspace=workspace)

        self.iteration = 0
        self.token_count = 0
        self.completed = False

    # --- public API ----------------------------------------------------------

    def run(self, prompt: str, is_recovery: bool = False) -> Iterator[Event]:
        """Run the agent, yielding events as they happen."""
        message = RECOVERY_PREFIX.format(context=prompt) if is_recovery else prompt
        self.context.add_user_text(message)

        yield self.events.emit(
            EventType.RUN_STARTED,
            prompt=prompt,
            recovery=is_recovery,
            model=self.config.model,
            max_iterations=self.config.max_iterations,
            tools=self.registry.names(),
        )

        consecutive_errors = 0
        nudges = 0

        for iteration in range(1, self.config.max_iterations + 1):
            self.iteration = iteration
            yield self.events.emit(
                EventType.ITERATION_STARTED,
                iteration=iteration,
                max_iterations=self.config.max_iterations,
                tokens=self.token_count,
            )

            yield from self._maybe_compress()
            yield from self._maybe_backup(iteration)

            try:
                turn = yield from self._run_turn()
            except PermanentAPIError as exc:
                yield from self._fail("permanent_api_error", str(exc), retryable=False)
                return
            except Exception as exc:  # noqa: BLE001 - transient, already retried
                consecutive_errors += 1
                yield self.events.emit(
                    EventType.WARNING,
                    message=f"Iteration {iteration} failed: {exc}",
                    consecutive_errors=consecutive_errors,
                )
                if consecutive_errors >= self.config.max_consecutive_errors:
                    yield from self._fail(
                        "repeated_failures",
                        f"{consecutive_errors} consecutive failures: {exc}",
                        retryable=True,
                    )
                    return
                continue

            consecutive_errors = 0

            if turn.usage.get("total"):
                self.token_count = turn.usage["total"]
                yield self.events.emit(EventType.USAGE_UPDATED, **turn.usage)

            if turn.content is not None:
                self.context.add_model_content(turn.content)

            if not turn.function_calls:
                # No tool call: the model is not allowed to end the run this way.
                nudges += 1
                if nudges > self.config.max_nudges:
                    yield self.events.emit(
                        EventType.RUN_NEEDS_INPUT,
                        question=turn.text.strip()
                        or "The agent stopped without calling finish_task.",
                        iteration=iteration,
                    )
                    return
                self.context.add_user_text(CONTINUE_NUDGE)
                yield self.events.emit(
                    EventType.WARNING,
                    message="Model replied without calling a tool; asking it to continue.",
                    nudge=nudges,
                )
                continue

            nudges = 0
            yield from self._run_tools(turn)

            if self.tool_ctx.question:
                yield self.events.emit(
                    EventType.RUN_NEEDS_INPUT,
                    question=self.tool_ctx.question,
                    iteration=iteration,
                )
                return

            if self.tool_ctx.finished:
                self.completed = True
                yield self.events.emit(
                    EventType.RUN_COMPLETED,
                    iteration=iteration,
                    tokens=self.token_count,
                    **self.tool_ctx.finished,
                )
                return

        # Loop exhausted without finish_task
        yield from self._save_snapshot("max_iterations")
        yield self.events.emit(
            EventType.RUN_FAILED,
            error_type="max_iterations",
            message=f"Reached the maximum of {self.config.max_iterations} iterations.",
            retryable=True,
            iteration=self.iteration,
        )

    def save_snapshot(self, reason: str) -> Iterator[Event]:
        """Public snapshot hook, used by the CLI on Ctrl+C."""
        yield from self._save_snapshot(reason)

    # --- internals -----------------------------------------------------------

    def _run_turn(self) -> Iterator[Event]:
        """Run one model turn, yielding deltas. Returns the TurnResult."""
        retries: List[Dict[str, Any]] = []

        def on_retry(attempt: int, delay: float, error: BaseException) -> None:
            retries.append({"attempt": attempt, "delay": round(delay, 1), "error": str(error)})

        tool = self.registry.gemini_tool()

        if self.config.stream:
            stream = self.llm.stream_turn(self.context.contents, tool, on_retry=on_retry)
            turn: Optional[TurnResult] = None
            while True:
                try:
                    kind, chunk = next(stream)
                except StopIteration as stop:
                    turn = stop.value
                    break
                if kind == "thinking":
                    yield self.events.emit(EventType.THINKING_DELTA, text=chunk)
                elif kind == "text":
                    yield self.events.emit(EventType.TEXT_DELTA, text=chunk)
        else:
            turn = self.llm.complete_turn(self.context.contents, tool, on_retry=on_retry)

        for retry in retries:
            yield self.events.emit(EventType.WARNING, message="API retry", **retry)

        return turn or TurnResult()

    def _run_tools(self, turn: TurnResult) -> Iterator[Event]:
        response_parts: List[types.Part] = []

        for call in turn.function_calls:
            name, args = call["name"], call["args"]
            yield self.events.emit(EventType.TOOL_CALL, name=name, args=_preview_args(args))

            spec = self.registry.get(name)
            if spec is None:
                result_text = f"Error: unknown tool '{name}'"
                ok, meta = False, {}
            else:
                result = spec.run(self.tool_ctx, args)
                result_text, ok, meta = result.message, result.ok, result.meta

            yield self.events.emit(
                EventType.TOOL_RESULT,
                name=name,
                ok=ok,
                result=_truncate(result_text, 400),
                meta=meta,
            )

            if meta.get("path") and meta.get("mode"):
                yield self.events.emit(
                    EventType.FILE_WRITTEN,
                    path=meta["path"],
                    words=meta.get("words", 0),
                    bytes=meta.get("bytes", 0),
                    mode=meta["mode"],
                )

            response_parts.append(
                types.Part.from_function_response(name=name, response={"result": result_text})
            )

        self.context.add_tool_results(response_parts)

    def _maybe_compress(self) -> Iterator[Event]:
        if self.token_count < self.config.compression_threshold:
            return

        result = self.context.compress()
        if not result.compressed:
            yield self.events.emit(
                EventType.WARNING, message=f"Compression skipped: {result.reason}"
            )
            return

        new_count = self.llm.count_tokens(self.context.contents)
        yield self.events.emit(
            EventType.CONTEXT_COMPRESSED,
            turns_before=result.contents_before,
            turns_after=result.contents_after,
            tokens_before=self.token_count,
            tokens_after=new_count,
            summary_chars=result.summary_chars,
        )
        self.token_count = new_count

    def _maybe_backup(self, iteration: int) -> Iterator[Event]:
        if self.config.backup_interval and iteration % self.config.backup_interval == 0:
            yield from self._save_snapshot("backup")

    def _save_snapshot(self, reason: str) -> Iterator[Event]:
        try:
            snapshot = self.context.snapshot()
        except Exception as exc:  # noqa: BLE001 - a failed snapshot must not mask the exit
            yield self.events.emit(EventType.WARNING, message=f"Snapshot failed: {exc}")
            return

        if snapshot is None:
            yield self.events.emit(
                EventType.WARNING, message="Snapshot skipped: not enough history yet."
            )
            return

        path, meta = snapshot
        yield self.events.emit(EventType.SNAPSHOT_SAVED, path=path, reason=reason, **meta)

    def _fail(self, error_type: str, message: str, retryable: bool) -> Iterator[Event]:
        yield from self._save_snapshot("failure")
        yield self.events.emit(
            EventType.RUN_FAILED,
            error_type=error_type,
            message=message,
            retryable=retryable,
            iteration=self.iteration,
        )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _preview_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Tool arguments can hold an entire chapter; events carry a preview."""
    return {key: _truncate(str(value), 160) for key, value in (args or {}).items()}
