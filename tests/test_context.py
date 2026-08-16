"""Context compression, turn boundaries and recovery snapshots."""

import pytest
from google.genai import types

from core.context import (
    SUMMARY_HEADER,
    ContextManager,
    find_cut_point,
    is_boundary,
    render_contents,
)
from tests.conftest import FakeLLM


def user(text):
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


def model_call(name, **args):
    return types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
    )


def tool_result(name, result):
    return types.Content(
        role="user", parts=[types.Part.from_function_response(name=name, response={"result": result})]
    )


def model_text(text):
    return types.Content(role="model", parts=[types.Part.from_text(text=text)])


@pytest.fixture
def manager(workspace):
    return ContextManager(FakeLLM(), workspace, keep_recent=2)


def build_history(manager, turns=4):
    manager.add_user_text("write a novel")
    for i in range(turns):
        manager.add_model_content(model_call("write_file", filename=f"ch{i}.md", content="x" * 5000))
        manager.add_tool_results(
            [types.Part.from_function_response(
                name="write_file", response={"result": f"Wrote ch{i}.md"}
            )]
        )
    return manager


# --- rendering --------------------------------------------------------------


def test_render_includes_tool_calls_and_results():
    contents = [
        user("write a novel"),
        model_call("write_file", filename="ch1.md", content="Once upon a time"),
        tool_result("write_file", "Wrote 'ch1.md' (3,200 words)"),
    ]
    text = render_contents(contents)

    assert "[Tool call] write_file(filename=ch1.md" in text
    assert "[Tool result] write_file: Wrote 'ch1.md'" in text


def test_render_truncates_long_arguments():
    contents = [model_call("write_file", filename="ch1.md", content="x" * 10_000)]
    text = render_contents(contents)

    assert len(text) < 500
    assert "..." in text


def test_render_marks_thinking():
    contents = [types.Content(role="model", parts=[types.Part(text="planning", thought=True)])]
    assert "[Thinking] planning" in render_contents(contents)


# --- turn boundaries (B-05) -------------------------------------------------


def test_tool_results_are_not_a_valid_cut_point():
    contents = [user("prompt"), model_call("write_file", filename="a.md"), tool_result("write_file", "ok")]

    assert is_boundary(contents, 1) is True   # before a model turn
    assert is_boundary(contents, 2) is False  # would orphan the function call


def test_plain_user_messages_are_a_valid_cut_point():
    contents = [user("prompt"), model_text("hello"), user("continue please")]
    assert is_boundary(contents, 2) is True


def test_cut_point_snaps_backwards_to_a_safe_index():
    contents = [
        user("prompt"),
        model_call("write_file", filename="a.md"),
        tool_result("write_file", "ok"),
        model_call("write_file", filename="b.md"),
        tool_result("write_file", "ok"),
    ]
    # index 2 and 4 are unsafe; the nearest safe cut at or before 4 is 3
    assert find_cut_point(contents, 4) == 3
    assert find_cut_point(contents, 2) == 1


# --- compression ------------------------------------------------------------


def test_compression_keeps_recent_turns_as_raw_content(manager):
    build_history(manager, turns=4)
    before = len(manager.contents)

    result = manager.compress()

    assert result.compressed
    assert len(manager.contents) < before
    # First message is the summary, the rest are the untouched Content objects.
    assert SUMMARY_HEADER in manager.contents[0].parts[0].text
    tail = manager.contents[1:]
    assert any(part.function_call for content in tail for part in content.parts or [])


def test_compression_never_orphans_a_function_call(manager):
    build_history(manager, turns=5)
    manager.compress()

    for index, content in enumerate(manager.contents):
        has_response = any(getattr(p, "function_response", None) for p in content.parts or [])
        if has_response:
            previous = manager.contents[index - 1]
            assert any(getattr(p, "function_call", None) for p in previous.parts or [])


def test_compression_summary_carries_the_original_request(manager):
    build_history(manager, turns=4)
    manager.compress()

    summary_text = manager.contents[0].parts[0].text
    assert "write a novel" in summary_text


def test_compression_injects_the_story_bible_and_file_list(manager, workspace):
    workspace.write("story_bible.md", "## Characters\n\n- Ada, 34", "create")
    workspace.write("ch0.md", "prose here", "create")
    build_history(manager, turns=4)

    manager.compress()

    summary_text = manager.contents[0].parts[0].text
    assert "Ada, 34" in summary_text
    assert "ch0.md" in summary_text


def test_compression_is_skipped_for_short_history(manager):
    manager.add_user_text("write a novel")
    result = manager.compress()

    assert not result.compressed
    assert result.reason == "history too short"


def test_compression_keeps_history_when_the_summary_is_empty(workspace):
    manager = ContextManager(FakeLLM(summary=""), workspace, keep_recent=2)
    build_history(manager, turns=4)
    before = list(manager.contents)

    result = manager.compress()

    assert not result.compressed
    assert manager.contents == before


# --- snapshots (B-01) -------------------------------------------------------


def test_snapshot_writes_a_recovery_file(manager, workspace):
    build_history(manager, turns=2)

    path, meta = manager.snapshot()

    text = open(path, encoding="utf-8").read()
    assert "SUMMARY" in text
    assert "write a novel" in text
    assert meta["turns"] == len(manager.contents)


def test_snapshot_summary_sees_the_tool_history(manager):
    build_history(manager, turns=2)
    manager.snapshot()

    transcript = manager.llm.summaries[0]
    assert "[Tool call] write_file" in transcript
    assert "ch0.md" in transcript


def test_snapshot_lists_files_on_disk(manager, workspace):
    workspace.write("ch0.md", "prose", "create")
    build_history(manager, turns=2)

    path, _ = manager.snapshot()

    assert "ch0.md" in open(path, encoding="utf-8").read()


def test_snapshot_needs_history(manager):
    manager.add_user_text("write a novel")
    assert manager.snapshot() is None


def test_snapshot_skips_empty_summaries(workspace):
    manager = ContextManager(FakeLLM(summary="   "), workspace, keep_recent=2)
    build_history(manager, turns=2)
    assert manager.snapshot() is None
