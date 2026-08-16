"""The agent loop, driven end to end by a scripted fake LLM."""

import pytest

from core.config import RunConfig
from core.context import SUMMARY_HEADER
from core.events import EventType
from core.llm import PermanentAPIError
from core.runner import AgentRunner
from tests.conftest import FakeLLM, turn


def build(workspace, turns, **config_kwargs):
    options = {"max_iterations": 10, "backup_interval": 0, **config_kwargs}
    config = RunConfig(**options)
    llm = FakeLLM(turns)
    return AgentRunner(llm=llm, workspace=workspace, config=config), llm


def collect(runner, prompt="write a short story", **kwargs):
    return list(runner.run(prompt, **kwargs))


def types_of(events):
    return [event.type for event in events]


def first(events, event_type):
    return next(event for event in events if event.type is event_type)


def only(events, event_type):
    return [event for event in events if event.type is event_type]


WRITE = ("write_file", {"filename": "ch1.md", "content": "Once upon a time", "mode": "create"})
FINISH = ("finish_task", {"summary": "Done."})


# --- happy path -------------------------------------------------------------


def test_run_writes_files_and_completes(workspace):
    runner, _ = build(workspace, [turn(calls=[WRITE]), turn(calls=[FINISH])])

    events = collect(runner)

    assert types_of(events)[0] is EventType.RUN_STARTED
    assert types_of(events)[-1] is EventType.RUN_COMPLETED
    assert workspace.read("ch1.md") == "Once upon a time"

    completed = first(events, EventType.RUN_COMPLETED)
    assert completed.data["summary"] == "Done."
    assert completed.data["files"] == ["ch1.md"]
    assert completed.data["total_words"] == 4


def test_file_written_events_carry_word_counts(workspace):
    runner, _ = build(workspace, [turn(calls=[WRITE]), turn(calls=[FINISH])])

    written = only(collect(runner), EventType.FILE_WRITTEN)

    assert len(written) == 1
    assert written[0].data == {"path": "ch1.md", "words": 4, "bytes": 16, "mode": "create"}


def test_streaming_deltas_are_emitted(workspace):
    runner, _ = build(
        workspace,
        [turn(text="Let me start.", thinking="planning the plot", calls=[FINISH])],
    )

    events = collect(runner)

    assert [e.data["text"] for e in only(events, EventType.THINKING_DELTA)] == ["planning the plot"]
    assert [e.data["text"] for e in only(events, EventType.TEXT_DELTA)] == ["Let me start."]


def test_events_are_sequentially_numbered(workspace):
    runner, _ = build(workspace, [turn(calls=[WRITE]), turn(calls=[FINISH])])
    events = collect(runner)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


def test_tool_results_are_fed_back_as_function_responses(workspace):
    runner, llm = build(workspace, [turn(calls=[WRITE]), turn(calls=[FINISH])])
    collect(runner)

    second_call = llm.calls[1]
    assert [c.role for c in second_call] == ["user", "model", "user"]
    assert second_call[1].parts[-1].function_call.name == "write_file"
    assert second_call[2].parts[0].function_response.name == "write_file"


def test_usage_is_tracked_from_the_turn(workspace):
    runner, _ = build(workspace, [turn(calls=[FINISH], tokens=4321)])
    usage = first(collect(runner), EventType.USAGE_UPDATED)
    assert usage.data["total"] == 4321


# --- completion detection (B-08) --------------------------------------------


def test_text_without_a_tool_call_does_not_end_the_run(workspace):
    """The old loop treated any text-only turn as success, ending mid-novel."""
    runner, _ = build(
        workspace,
        [turn(text="Here is my plan."), turn(calls=[WRITE]), turn(calls=[FINISH])],
    )

    events = collect(runner)

    assert types_of(events)[-1] is EventType.RUN_COMPLETED
    assert workspace.exists("ch1.md")
    assert any("without calling a tool" in e.data.get("message", "") for e in only(events, EventType.WARNING))


def test_repeated_silence_asks_the_user_instead_of_pretending_success(workspace):
    runner, _ = build(
        workspace,
        [turn(text="I am unsure."), turn(text="Still unsure."), turn(text="Really unsure.")],
        max_nudges=2,
    )

    events = collect(runner)

    assert types_of(events)[-1] is EventType.RUN_NEEDS_INPUT
    assert "unsure" in first(events, EventType.RUN_NEEDS_INPUT).data["question"].lower()


def test_ask_user_pauses_the_run(workspace):
    runner, _ = build(
        workspace, [turn(calls=[("ask_user", {"question": "First or third person?"})])]
    )

    events = collect(runner)

    assert types_of(events)[-1] is EventType.RUN_NEEDS_INPUT
    assert first(events, EventType.RUN_NEEDS_INPUT).data["question"] == "First or third person?"


def test_unknown_tool_is_reported_without_crashing(workspace):
    runner, _ = build(workspace, [turn(calls=[("teleport", {})]), turn(calls=[FINISH])])

    events = collect(runner)

    result = first(events, EventType.TOOL_RESULT)
    assert result.data["ok"] is False
    assert "unknown tool" in result.data["result"].lower()
    assert types_of(events)[-1] is EventType.RUN_COMPLETED


def test_tool_failure_is_reported_and_the_run_continues(workspace):
    bad_write = ("write_file", {"filename": "../escape.md", "content": "x", "mode": "create"})
    runner, _ = build(workspace, [turn(calls=[bad_write]), turn(calls=[FINISH])])

    events = collect(runner)

    assert first(events, EventType.TOOL_RESULT).data["ok"] is False
    assert types_of(events)[-1] is EventType.RUN_COMPLETED


# --- failures (B-06) --------------------------------------------------------


def test_permanent_error_fails_the_run_and_snapshots(workspace):
    runner, _ = build(
        workspace, [turn(calls=[WRITE]), PermanentAPIError("400 API key not valid")]
    )

    events = collect(runner)

    assert types_of(events)[-1] is EventType.RUN_FAILED
    assert first(events, EventType.RUN_FAILED).data["error_type"] == "permanent_api_error"
    assert only(events, EventType.SNAPSHOT_SAVED)


def test_transient_errors_are_tolerated_then_the_run_continues(workspace):
    runner, _ = build(
        workspace,
        [RuntimeError("503 unavailable"), turn(calls=[WRITE]), turn(calls=[FINISH])],
    )

    events = collect(runner)

    assert types_of(events)[-1] is EventType.RUN_COMPLETED
    assert any("failed" in e.data.get("message", "") for e in only(events, EventType.WARNING))


def test_consecutive_failures_stop_the_run(workspace):
    runner, _ = build(
        workspace, [RuntimeError("503 unavailable") for _ in range(10)], max_consecutive_errors=3
    )

    events = collect(runner)
    failed = first(events, EventType.RUN_FAILED)

    assert failed.data["error_type"] == "repeated_failures"
    iteration_failures = [
        e for e in only(events, EventType.WARNING) if "failed:" in e.data.get("message", "")
    ]
    assert len(iteration_failures) == 3


def test_max_iterations_fails_with_a_snapshot(workspace):
    runner, _ = build(workspace, [turn(calls=[WRITE]) for _ in range(3)], max_iterations=3)

    events = collect(runner)

    assert first(events, EventType.RUN_FAILED).data["error_type"] == "max_iterations"
    assert only(events, EventType.SNAPSHOT_SAVED)


# --- context management -----------------------------------------------------


def test_compression_runs_when_the_threshold_is_crossed(workspace):
    runner, llm = build(
        workspace,
        [
            turn(calls=[WRITE], tokens=900),
            turn(calls=[WRITE], tokens=900),
            turn(calls=[WRITE], tokens=900),
            turn(calls=[FINISH]),
        ],
        token_limit=1000,
        compression_ratio=0.5,
        keep_recent_contents=2,
    )

    events = collect(runner)
    compressed = only(events, EventType.CONTEXT_COMPRESSED)

    assert compressed
    assert compressed[0].data["summary_chars"] > 0
    assert llm.summaries  # the summarizer was actually called

    # The compressed history is what the model actually receives next, and it
    # still starts from the durable summary rather than the raw prefix.
    next_history = llm.calls[-1]
    assert SUMMARY_HEADER in next_history[0].parts[0].text
    assert "write a short story" in next_history[0].parts[0].text


def test_compression_does_not_run_below_the_threshold(workspace):
    runner, llm = build(workspace, [turn(calls=[WRITE], tokens=10), turn(calls=[FINISH])])

    events = collect(runner)

    assert not only(events, EventType.CONTEXT_COMPRESSED)
    assert llm.summaries == []


def test_backup_snapshots_are_written_on_interval(workspace):
    config_turns = [turn(calls=[WRITE]), turn(calls=[WRITE]), turn(calls=[FINISH])]
    runner, _ = build(workspace, config_turns)
    runner.config.backup_interval = 2

    events = collect(runner)
    snapshots = only(events, EventType.SNAPSHOT_SAVED)

    assert snapshots
    assert snapshots[0].data["reason"] == "backup"
    assert list(workspace.project_dir.glob(".context_summary_*.md"))


def test_manual_snapshot_hook_for_interrupts(workspace):
    runner, _ = build(workspace, [turn(calls=[WRITE]), turn(calls=[FINISH])])
    collect(runner)

    events = list(runner.save_snapshot("interrupted"))

    assert events[-1].type is EventType.SNAPSHOT_SAVED
    assert events[-1].data["reason"] == "interrupted"


# --- recovery ---------------------------------------------------------------


def test_recovery_mode_wraps_the_saved_context(workspace):
    runner, llm = build(workspace, [turn(calls=[FINISH])])

    collect(runner, prompt="previous summary text", is_recovery=True)

    first_message = llm.calls[0][0].parts[0].text
    assert "[RECOVERED CONTEXT]" in first_message
    assert "previous summary text" in first_message


def test_run_started_event_lists_the_tools(workspace):
    runner, _ = build(workspace, [turn(calls=[FINISH])])
    started = first(collect(runner), EventType.RUN_STARTED)

    assert "write_file" in started.data["tools"]
    assert "finish_task" in started.data["tools"]


# --- non-streaming mode -----------------------------------------------------


def test_non_streaming_mode_still_completes(workspace):
    runner, _ = build(workspace, [turn(calls=[WRITE]), turn(calls=[FINISH])], stream=False)

    events = collect(runner)

    assert types_of(events)[-1] is EventType.RUN_COMPLETED
    assert not only(events, EventType.TEXT_DELTA)


@pytest.mark.parametrize("stream", [True, False])
def test_both_modes_produce_the_same_files(workspace, stream):
    runner, _ = build(workspace, [turn(calls=[WRITE]), turn(calls=[FINISH])], stream=stream)
    collect(runner)
    assert workspace.read("ch1.md") == "Once upon a time"
