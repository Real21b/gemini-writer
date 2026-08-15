"""Agent loop helpers: history flattening and tool dispatch."""

from google.genai import types

import writer
from tools.project import sanitize_folder_name


def _content(role, text):
    return types.Content(role=role, parts=[types.Part.from_text(text=text)])


def test_to_simple_messages_includes_system_prompt():
    contents = [_content("user", "write a novel"), _content("model", "starting")]
    messages = writer.to_simple_messages(contents, "SYSTEM")

    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    assert [m["content"] for m in messages[1:]] == ["write a novel", "starting"]


def test_to_simple_messages_renders_tool_calls_and_results():
    contents = [
        types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(
                name="write_file", args={"filename": "a.md", "content": "long text"}
            ))],
        ),
        types.Content(
            role="user",
            parts=[types.Part.from_function_response(name="write_file", response={"result": "ok"})],
        ),
    ]
    messages = writer.to_simple_messages(contents)

    assert messages[0]["content"].startswith("[Tool call] write_file(")
    assert "filename=a.md" in messages[0]["content"]
    assert messages[1]["content"] == "[Tool result] write_file: ok"


def test_to_simple_messages_truncates_long_arguments():
    chapter = "x" * 10_000
    contents = [
        types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(
                name="write_file", args={"content": chapter}
            ))],
        )
    ]
    rendered = writer.to_simple_messages(contents)[0]["content"]

    assert len(rendered) < 300
    assert rendered.endswith("...)")


def test_to_simple_messages_skips_empty_parts():
    contents = [types.Content(role="user", parts=[]), _content("user", "keep me")]
    assert writer.to_simple_messages(contents) == [{"role": "user", "content": "keep me"}]


def test_execute_tool_calls_the_mapped_function(fake_client):
    calls = {}

    def fake_write(**kwargs):
        calls.update(kwargs)
        return "written"

    result = writer.execute_tool(
        "write_file", {"filename": "a.md"}, {"write_file": fake_write}, [], "SYSTEM", fake_client
    )

    assert result == "written"
    assert calls == {"filename": "a.md"}


def test_execute_tool_reports_unknown_tools(fake_client):
    result = writer.execute_tool("nope", {}, {}, [], "SYSTEM", fake_client)
    assert "Unknown tool" in result


def test_execute_tool_survives_bad_arguments(fake_client):
    def fake_write(filename):
        return "written"

    result = writer.execute_tool(
        "write_file", {"unexpected": 1}, {"write_file": fake_write}, [], "SYSTEM", fake_client
    )

    assert result.startswith("Error: Invalid arguments")


def test_execute_tool_survives_tool_exceptions(fake_client):
    def exploding(**_kwargs):
        raise ValueError("kaboom")

    result = writer.execute_tool(
        "write_file", {}, {"write_file": exploding}, [], "SYSTEM", fake_client
    )

    assert "kaboom" in result
    assert result.startswith("Error:")


def test_execute_tool_routes_compression_internally(active_project, fake_client):
    """compress_context must never be dispatched with model supplied arguments."""
    called = []

    contents = [_content("user", f"message {i}") for i in range(6)]
    result = writer.execute_tool(
        "compress_context",
        {},
        {"compress_context": lambda **kw: called.append(kw)},
        contents,
        "SYSTEM",
        fake_client,
    )

    assert called == []
    assert "compress" in result.lower()


def test_compress_if_needed_is_a_noop_below_the_threshold(fake_client):
    contents = [_content("user", "hello")]
    new_contents, tokens = writer.compress_if_needed(contents, "SYSTEM", fake_client, 100)

    assert new_contents is contents
    assert tokens == 100
    assert fake_client.models.calls == []


def test_sanitize_folder_name():
    assert sanitize_folder_name("My Great Novel!") == "My_Great_Novel"
    assert sanitize_folder_name("  ../etc  ") == "etc"
    assert sanitize_folder_name("***") == "untitled_project"
