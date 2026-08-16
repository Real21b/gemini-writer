"""CLI argument handling, exit codes and the console renderer."""

import io

import pytest

from cli import main as cli_main
from cli.renderer import ConsoleRenderer
from core.events import Event, EventType
from tests.conftest import FakeLLM, turn

PROJECT = ("create_project", {"project_name": "story"})
WRITE = ("write_file", {"filename": "ch1.md", "content": "Once upon a time", "mode": "create"})
FINISH = ("finish_task", {"summary": "Done."})


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """Runs the CLI against a fake LLM and a throwaway output directory."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_WRITER_OUTPUT_DIR", raising=False)
    monkeypatch.setattr(cli_main.genai, "Client", lambda **_kwargs: object())

    state = {}

    def run(turns, argv=None):
        llm = FakeLLM(turns)
        state["llm"] = llm
        monkeypatch.setattr(cli_main, "GeminiLLM", lambda *_a, **_kw: llm)
        args = list(argv or ["write a short story"])
        args += ["--output-dir", str(tmp_path / "output")]
        return cli_main.main(args)

    run.tmp_path = tmp_path
    run.state = state
    return run


# --- argument parsing --------------------------------------------------------


def test_parser_defaults():
    args = cli_main.build_parser().parse_args(["write a novel"])
    assert args.prompt == "write a novel"
    assert args.recover is None
    assert args.no_stream is False


def test_run_config_overrides_from_flags():
    from core.config import Settings

    args = cli_main.build_parser().parse_args(
        ["prompt", "--model", "custom-model", "--max-iterations", "7",
         "--temperature", "0.3", "--thinking", "LOW", "--no-stream"]
    )
    settings = Settings(api_key="k", output_root=cli_main.Path("/tmp"), model="default-model")

    config = cli_main.build_run_config(args, settings)

    assert config.model == "custom-model"
    assert config.max_iterations == 7
    assert config.temperature == 0.3
    assert config.thinking_level == "LOW"
    assert config.stream is False


def test_run_config_falls_back_to_settings_model():
    from core.config import Settings

    args = cli_main.build_parser().parse_args(["prompt"])
    settings = Settings(api_key="k", output_root=cli_main.Path("/tmp"), model="env-model")

    assert cli_main.build_run_config(args, settings).model == "env-model"


def test_missing_recovery_file_exits(monkeypatch, tmp_path):
    args = cli_main.build_parser().parse_args(["--recover", str(tmp_path / "nope.md")])
    with pytest.raises(SystemExit) as exc:
        cli_main.resolve_prompt(args)
    assert exc.value.code == cli_main.EXIT_FAILED


def test_recovery_file_is_loaded(tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text("previous work", encoding="utf-8")

    args = cli_main.build_parser().parse_args(["--recover", str(summary)])
    prompt, is_recovery = cli_main.resolve_prompt(args)

    assert is_recovery is True
    assert prompt == "previous work"


def test_missing_api_key_is_reported(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert cli_main.main(["write a novel"]) == cli_main.EXIT_FAILED
    assert "GEMINI_API_KEY" in capsys.readouterr().out


# --- full CLI runs -----------------------------------------------------------


def test_successful_run_writes_files_and_exits_zero(cli_env, capsys):
    code = cli_env([turn(calls=[PROJECT, WRITE]), turn(calls=[FINISH])])

    assert code == cli_main.EXIT_OK
    out = capsys.readouterr().out
    assert "TASK COMPLETED" in out
    assert "ch1.md" in out

    projects = list((cli_env.tmp_path / "output").iterdir())
    assert projects and (projects[0] / "ch1.md").exists()


def test_failed_run_exits_one(cli_env, capsys):
    from core.llm import PermanentAPIError

    code = cli_env([turn(calls=[PROJECT, WRITE]), PermanentAPIError("400 API key not valid")])

    assert code == cli_main.EXIT_FAILED
    out = capsys.readouterr().out
    assert "RUN FAILED" in out
    assert "--recover" in out  # the recovery hint points at the snapshot


def test_needs_input_exits_two(cli_env, capsys):
    code = cli_env([turn(calls=[PROJECT, ("ask_user", {"question": "Which ending?"})])])

    assert code == cli_main.EXIT_NEEDS_INPUT
    assert "Which ending?" in capsys.readouterr().out


def test_interrupt_saves_a_snapshot(cli_env, capsys):
    code = cli_env([turn(calls=[PROJECT, WRITE]), KeyboardInterrupt()])

    assert code == cli_main.EXIT_OK
    out = capsys.readouterr().out
    assert "Interrupted" in out
    assert "Snapshot saved" in out
    assert "--recover" in out


def test_no_stream_flag_disables_deltas(cli_env, capsys):
    cli_env(
        [turn(text="thinking out loud", calls=[PROJECT, FINISH])],
        argv=["write a short story", "--no-stream"],
    )
    assert "💬" not in capsys.readouterr().out


# --- renderer ----------------------------------------------------------------


def render(events, verbose=False):
    stream = io.StringIO()
    renderer = ConsoleRenderer(stream=stream, verbose=verbose)
    for event in events:
        renderer.handle(event)
    return stream.getvalue(), renderer


def test_renderer_streams_deltas_on_one_line():
    output, _ = render(
        [
            Event(EventType.TEXT_DELTA, {"text": "Once "}),
            Event(EventType.TEXT_DELTA, {"text": "upon a time"}),
        ]
    )
    assert output == "💬 Once upon a time"


def test_renderer_closes_the_delta_line_before_a_block_event():
    output, _ = render(
        [
            Event(EventType.TEXT_DELTA, {"text": "writing"}),
            Event(EventType.TOOL_CALL, {"name": "write_file", "args": {"filename": "a.md"}}),
        ]
    )
    assert output == "💬 writing\n🔧 write_file(filename=a.md)\n"


def test_renderer_switches_between_thinking_and_text():
    output, _ = render(
        [
            Event(EventType.THINKING_DELTA, {"text": "planning"}),
            Event(EventType.TEXT_DELTA, {"text": "prose"}),
        ]
    )
    assert output == "🧠 planning\n💬 prose"


def test_renderer_reports_files_and_snapshots():
    output, renderer = render(
        [
            Event(EventType.FILE_WRITTEN, {"path": "ch1.md", "words": 3200, "bytes": 18000, "mode": "create"}),
            Event(EventType.SNAPSHOT_SAVED, {"path": "/tmp/x.md", "reason": "backup"}),
        ]
    )
    assert "ch1.md — 3,200 words (create)" in output
    assert renderer.snapshot_path == "/tmp/x.md"


def test_renderer_hides_usage_unless_verbose():
    quiet, _ = render([Event(EventType.USAGE_UPDATED, {"total": 100})])
    loud, _ = render([Event(EventType.USAGE_UPDATED, {"total": 100})], verbose=True)

    assert quiet == ""
    assert "100" in loud


def test_renderer_shows_unknown_events_only_in_verbose_mode():
    quiet, _ = render([Event(EventType.ITERATION_STARTED, {"iteration": 1, "max_iterations": 5})])
    assert "Iteration 1/5" in quiet
