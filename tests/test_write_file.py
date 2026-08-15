"""Behaviour of the write_file tool."""

from tools.paths import MAX_FILE_BYTES
from tools.writer import write_file_impl


def test_create_writes_file(active_project):
    result = write_file_impl("chapter_01.md", "Once upon a time", "create")
    assert result.startswith("Successfully created")
    assert (active_project / "chapter_01.md").read_text(encoding="utf-8") == "Once upon a time"


def test_create_twice_fails(active_project):
    write_file_impl("chapter_01.md", "first", "create")
    result = write_file_impl("chapter_01.md", "second", "create")
    assert result.startswith("Error:")
    assert (active_project / "chapter_01.md").read_text(encoding="utf-8") == "first"


def test_append_adds_content(active_project):
    write_file_impl("chapter_01.md", "start", "create")
    result = write_file_impl("chapter_01.md", " and end", "append")
    assert result.startswith("Successfully appended")
    assert (active_project / "chapter_01.md").read_text(encoding="utf-8") == "start and end"


def test_overwrite_replaces_content(active_project):
    write_file_impl("chapter_01.md", "old", "create")
    write_file_impl("chapter_01.md", "new", "overwrite")
    assert (active_project / "chapter_01.md").read_text(encoding="utf-8") == "new"


def test_missing_extension_gets_markdown(active_project):
    write_file_impl("chapter_02", "text", "create")
    assert (active_project / "chapter_02.md").exists()


def test_subdirectory_is_created(active_project):
    write_file_impl("chapters/chapter_03.md", "text", "create")
    assert (active_project / "chapters" / "chapter_03.md").exists()


def test_traversal_does_not_write_outside(active_project):
    outside = active_project.parent / "escape.md"
    result = write_file_impl("../escape.md", "pwned", "create")
    assert result.startswith("Error:")
    assert not outside.exists()


def test_invalid_mode_is_rejected(active_project):
    result = write_file_impl("chapter_01.md", "text", "delete")
    assert result.startswith("Error: Invalid mode")
    assert not (active_project / "chapter_01.md").exists()


def test_oversized_content_is_rejected(active_project):
    result = write_file_impl("huge.md", "x" * (MAX_FILE_BYTES + 1), "create")
    assert result.startswith("Error:")
    assert not (active_project / "huge.md").exists()


def test_without_project_folder_returns_error(tmp_path):
    from tools import project as project_module

    project_module.set_active_project_folder(None)
    result = write_file_impl("chapter_01.md", "text", "create")
    assert "No active project folder" in result
