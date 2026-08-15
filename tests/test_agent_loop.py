"""End-to-end agent loop tests driven by a scripted fake model."""

from types import SimpleNamespace

import pytest
from google.genai import types

import utils
import writer


def text_part(text):
    return types.Part.from_text(text=text)


def call_part(name, **args):
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def model_turn(parts, total_tokens=1000):
    """A model response carrying the given parts."""
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=total_tokens // 2,
            candidates_token_count=total_tokens // 2,
            thoughts_token_count=0,
            total_token_count=total_tokens,
        ),
    )


class ScriptedModels:
    """Replays a scripted list of agent turns; summary calls are answered separately."""

    def __init__(self, turns, summary_text="SUMMARY"):
        self.turns = list(turns)
        self.summary_text = summary_text
        self.agent_calls = 0
        self.summary_calls = 0
        self.agent_contents = []
        self.summary_prompts = []

    def generate_content(self, model, contents, config=None):
        # Summarizer calls are the ones made without tools.
        if config is None or not getattr(config, "tools", None):
            self.summary_calls += 1
            self.summary_prompts.append(contents[0].parts[0].text)
            return SimpleNamespace(text=self.summary_text)

        self.agent_calls += 1
        self.agent_contents.append(list(contents))
        if not self.turns:
            raise AssertionError("The agent asked for more turns than the script provides")
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        return turn

    def count_tokens(self, model, contents):
        return SimpleNamespace(total_tokens=42)


class ScriptedClient:
    def __init__(self, turns, summary_text="SUMMARY"):
        self.models = ScriptedModels(turns, summary_text)


@pytest.fixture
def run_agent(monkeypatch, active_project):
    """Runs writer.main() against a scripted client and records tool calls."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(utils.time, "sleep", lambda _seconds: None)

    tool_calls = []

    def fake_tool(name):
        def _call(**kwargs):
            tool_calls.append((name, kwargs))
            return f"{name} ok"

        return _call

    monkeypatch.setattr(
        writer,
        "get_tool_map",
        lambda: {"create_project": fake_tool("create_project"), "write_file": fake_tool("write_file")},
    )

    def _run(turns, argv=("writer.py", "write a short story"), summary_text="SUMMARY"):
        client = ScriptedClient(turns, summary_text)
        monkeypatch.setattr(writer.genai, "Client", lambda **_kwargs: client)
        monkeypatch.setattr("sys.argv", list(argv))
        writer.main()
        return client, tool_calls

    _run.tool_calls = tool_calls
    return _run


def test_happy_path_runs_tools_then_completes(run_agent, capsys):
    turns = [
        model_turn([
            call_part("create_project", project_name="My Story"),
            call_part("write_file", filename="story.md", content="Once...", mode="create"),
        ]),
        model_turn([text_part("All done - the story is written.")]),
    ]

    client, tool_calls = run_agent(turns)

    assert [name for name, _ in tool_calls] == ["create_project", "write_file"]
    assert client.models.agent_calls == 2
    assert "TASK COMPLETED" in capsys.readouterr().out


def test_tool_results_are_fed_back_to_the_model(run_agent):
    turns = [
        model_turn([call_part("write_file", filename="a.md", content="x", mode="create")]),
        model_turn([text_part("done")]),
    ]
    client, _ = run_agent(turns)

    # The second call carries: the prompt, the model's tool call turn (raw, so
    # thought signatures survive) and the tool results.
    second_call = client.models.agent_contents[1]
    assert [c.role for c in second_call] == ["user", "model", "user"]
    assert second_call[1].parts[0].function_call.name == "write_file"
    assert second_call[2].parts[0].function_response.name == "write_file"


def test_snapshot_records_which_files_were_written(run_agent, monkeypatch):
    """A recovery summary is useless without the file history (B-01/B-04)."""
    monkeypatch.setattr(writer, "BACKUP_INTERVAL", 2)
    turns = [
        model_turn([call_part("write_file", filename="chapter_01.md", content="x" * 5000, mode="create")]),
        model_turn([text_part("done")]),
    ]

    client, _ = run_agent(turns)

    prompt = client.models.summary_prompts[0]
    assert "[Tool call] write_file" in prompt
    assert "chapter_01.md" in prompt
    assert "[Tool result] write_file" in prompt
    assert "x" * 200 not in prompt  # long arguments are truncated


def test_transient_errors_are_retried_then_the_run_continues(run_agent, capsys):
    turns = [
        RuntimeError("503 Service Unavailable"),
        model_turn([call_part("write_file", filename="a.md", content="x", mode="create")]),
        model_turn([text_part("done")]),
    ]

    client, tool_calls = run_agent(turns)

    assert client.models.agent_calls == 3
    assert [name for name, _ in tool_calls] == ["write_file"]
    out = capsys.readouterr().out
    assert "Retry" in out and "TASK COMPLETED" in out


def test_permanent_error_stops_the_run_and_saves_a_snapshot(run_agent, active_project, capsys):
    turns = [
        model_turn([call_part("write_file", filename="a.md", content="x", mode="create")]),
        RuntimeError("400 API key not valid"),
    ]

    with pytest.raises(SystemExit) as exc:
        run_agent(turns)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Unrecoverable API error" in out
    assert list(active_project.glob(".context_summary_*.md"))
    assert "--recover" in out


def test_run_stops_after_consecutive_failures(run_agent, monkeypatch, capsys):
    monkeypatch.setattr(writer, "API_MAX_ATTEMPTS", 2)
    turns = [RuntimeError("503 unavailable") for _ in range(40)]

    with pytest.raises(SystemExit) as exc:
        run_agent(turns)

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"{writer.MAX_CONSECUTIVE_ERRORS} consecutive failures" in out


def test_context_is_compressed_when_the_threshold_is_crossed(run_agent, monkeypatch, capsys):
    monkeypatch.setattr(writer, "COMPRESSION_THRESHOLD", 500)
    turns = [
        model_turn([call_part("write_file", filename="a.md", content="x", mode="create")], total_tokens=900),
        model_turn([text_part("done")], total_tokens=900),
    ]

    client, _ = run_agent(turns)

    assert client.models.summary_calls >= 1
    assert "Compressing context" in capsys.readouterr().out


def test_backup_snapshot_is_written_on_interval(run_agent, monkeypatch, active_project, capsys):
    monkeypatch.setattr(writer, "BACKUP_INTERVAL", 2)
    turns = [
        model_turn([call_part("write_file", filename="a.md", content="x", mode="create")]),
        model_turn([text_part("done")]),
    ]

    run_agent(turns)

    assert list(active_project.glob(".context_summary_*.md"))
    assert "Backup saved" in capsys.readouterr().out


def test_keyboard_interrupt_saves_a_recovery_snapshot(run_agent, active_project, capsys):
    turns = [
        model_turn([call_part("write_file", filename="a.md", content="x", mode="create")]),
        KeyboardInterrupt(),
    ]

    with pytest.raises(SystemExit) as exc:
        run_agent(turns)

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Interrupted by user" in out
    assert "--recover" in out
    assert list(active_project.glob(".context_summary_*.md"))
