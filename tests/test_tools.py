"""Tool registry, schema generation and the individual tools."""

import pytest
from google.genai import types
from pydantic import BaseModel, Field

from core.tools import REGISTRY, ToolContext, pydantic_to_genai_schema
from core.tools.bible import BIBLE_FILENAME, merge_section, section_index


@pytest.fixture
def ctx(workspace) -> ToolContext:
    return ToolContext(workspace=workspace)


def run_tool(ctx, name, **args):
    spec = REGISTRY.get(name)
    assert spec is not None, f"tool '{name}' is not registered"
    return spec.run(ctx, args)


# --- registry and schema (B-12) ---------------------------------------------


def test_every_expected_tool_is_registered():
    assert set(REGISTRY.names()) == {
        "apply_patch",
        "ask_user",
        "create_project",
        "finish_task",
        "list_files",
        "read_file",
        "read_story_bible",
        "update_story_bible",
        "write_file",
    }


def test_gemini_tool_declares_all_functions():
    declarations = REGISTRY.gemini_tool().function_declarations
    assert {d.name for d in declarations} == set(REGISTRY.names())
    assert all(d.description for d in declarations)


def test_schema_is_derived_from_the_pydantic_model():
    class Args(BaseModel):
        name: str = Field(description="a name")
        count: int = 3
        flag: bool = False

    schema = pydantic_to_genai_schema(Args)

    assert schema.type == types.Type.OBJECT
    assert schema.properties["name"].type == types.Type.STRING
    assert schema.properties["name"].description == "a name"
    assert schema.properties["count"].type == types.Type.INTEGER
    assert schema.properties["flag"].type == types.Type.BOOLEAN
    assert schema.required == ["name"]


def test_schema_handles_literals_optionals_and_lists():
    from typing import List, Literal, Optional

    class Args(BaseModel):
        mode: Literal["create", "append"] = "create"
        tail: Optional[int] = None
        files: Optional[List[str]] = None

    schema = pydantic_to_genai_schema(Args)

    assert schema.properties["mode"].enum == ["create", "append"]
    assert schema.properties["tail"].type == types.Type.INTEGER
    assert schema.properties["files"].type == types.Type.ARRAY
    assert schema.properties["files"].items.type == types.Type.STRING


def test_write_file_schema_matches_the_implementation():
    declaration = REGISTRY.get("write_file").declaration()
    properties = declaration.parameters.properties

    assert set(properties) == {"filename", "content", "mode"}
    assert properties["mode"].enum == ["create", "append", "overwrite"]
    assert declaration.parameters.required == ["filename", "content"]


# --- argument validation ----------------------------------------------------


def test_missing_arguments_are_reported_not_raised(ctx):
    result = run_tool(ctx, "write_file", filename="a.md")
    assert not result.ok
    assert "invalid arguments" in result.message.lower()
    assert "content" in result.message


def test_invalid_enum_value_is_reported(ctx):
    result = run_tool(ctx, "write_file", filename="a.md", content="x", mode="delete")
    assert not result.ok


def test_tool_errors_are_returned_to_the_model(ctx):
    result = run_tool(ctx, "write_file", filename="../escape.md", content="x", mode="create")
    assert not result.ok
    assert "traversal" in result.message.lower()


# --- file tools -------------------------------------------------------------


def test_create_project_activates_the_workspace(empty_workspace):
    ctx = ToolContext(workspace=empty_workspace)
    result = run_tool(ctx, "create_project", project_name="My Novel")

    assert result.ok
    assert empty_workspace.is_ready
    assert result.meta["existed"] is False


def test_write_file_reports_metadata_for_events(ctx):
    result = run_tool(ctx, "write_file", filename="ch1.md", content="one two three", mode="create")

    assert result.meta == {"path": "ch1.md", "bytes": 13, "words": 3, "mode": "create"}


def test_read_file_returns_content(ctx):
    run_tool(ctx, "write_file", filename="ch1.md", content="Chapter one", mode="create")
    result = run_tool(ctx, "read_file", filename="ch1.md")
    assert result.message == "Chapter one"


def test_read_file_tail_supports_continuity_checks(ctx):
    run_tool(ctx, "write_file", filename="ch1.md", content="start ... the door closed.", mode="create")
    result = run_tool(ctx, "read_file", filename="ch1.md", tail_chars=16)
    assert result.message == "the door closed."


def test_list_files_summarizes_the_project(ctx):
    run_tool(ctx, "write_file", filename="ch1.md", content="one two", mode="create")
    run_tool(ctx, "write_file", filename="ch2.md", content="three", mode="create")

    result = run_tool(ctx, "list_files")

    assert "ch1.md" in result.message and "ch2.md" in result.message
    assert result.meta["count"] == 2
    assert result.meta["total_words"] == 3


def test_list_files_on_empty_project(ctx):
    assert "empty" in run_tool(ctx, "list_files").message


def test_apply_patch_edits_in_place(ctx):
    run_tool(ctx, "write_file", filename="ch1.md", content="Ada was tall.", mode="create")
    result = run_tool(ctx, "apply_patch", filename="ch1.md", old_text="tall", new_text="short")

    assert result.ok
    assert ctx.workspace.read("ch1.md") == "Ada was short."


# --- story bible (B-04) -----------------------------------------------------


def test_story_bible_is_created_with_a_template(ctx):
    result = run_tool(ctx, "update_story_bible", section="Characters", content="- Ada, 34, botanist")

    assert result.ok
    text = ctx.workspace.read(BIBLE_FILENAME)
    assert "- Ada, 34, botanist" in section_index(text)["Characters"]
    assert "Timeline" in section_index(text)


def test_story_bible_appends_without_losing_earlier_facts(ctx):
    run_tool(ctx, "update_story_bible", section="Characters", content="- Ada, 34")
    run_tool(ctx, "update_story_bible", section="Characters", content="- Cem, 41")
    run_tool(ctx, "update_story_bible", section="Places", content="- The lighthouse")

    sections = section_index(ctx.workspace.read(BIBLE_FILENAME))
    assert "Ada" in sections["Characters"] and "Cem" in sections["Characters"]
    assert "lighthouse" in sections["Places"]


def test_story_bible_replace_mode(ctx):
    run_tool(ctx, "update_story_bible", section="Premise", content="old premise")
    run_tool(ctx, "update_story_bible", section="Premise", content="new premise", mode="replace")

    sections = section_index(ctx.workspace.read(BIBLE_FILENAME))
    assert sections["Premise"] == "new premise"


def test_reading_a_missing_bible_is_not_an_error(ctx):
    result = run_tool(ctx, "read_story_bible")
    assert result.ok
    assert result.meta["exists"] is False


def test_merge_section_is_case_insensitive():
    text = "# Story Bible\n\n## Characters\n\n- Ada\n"
    merged = merge_section(text, "characters", "- Cem", "append")
    assert section_index(merged)["Characters"] == "- Ada\n\n- Cem"


def test_merge_section_creates_unknown_sections():
    merged = merge_section("# Story Bible\n", "Weather", "- foggy", "append")
    assert section_index(merged)["Weather"] == "- foggy"


# --- control tools (B-08) ---------------------------------------------------


def test_finish_task_marks_the_run_complete(ctx):
    run_tool(ctx, "write_file", filename="ch1.md", content="one two three", mode="create")
    result = run_tool(ctx, "finish_task", summary="Done.", files_written=["ch1.md"])

    assert result.ok
    assert ctx.finished["summary"] == "Done."
    assert ctx.finished["files"] == ["ch1.md"]
    assert ctx.finished["total_words"] == 3


def test_finish_task_defaults_to_the_files_on_disk(ctx):
    run_tool(ctx, "write_file", filename="ch1.md", content="x", mode="create")
    run_tool(ctx, "finish_task", summary="Done.")
    assert ctx.finished["files"] == ["ch1.md"]


def test_ask_user_records_the_question(ctx):
    run_tool(ctx, "ask_user", question="First person or third?")
    assert ctx.question == "First person or third?"
