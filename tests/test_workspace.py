"""Workspace: path safety, file operations and per-run isolation."""

import pytest

from core.workspace import (
    MAX_FILE_BYTES,
    NoProjectError,
    UnsafePathError,
    Workspace,
    WorkspaceError,
    normalize_filename,
    sanitize_folder_name,
)


# --- path safety (B-02) -----------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.md",
        "../../etc/passwd.md",
        "chapters/../../escape.md",
        "..\\..\\escape.md",
        "./../escape.md",
    ],
)
def test_traversal_is_rejected(workspace, filename):
    with pytest.raises(UnsafePathError):
        workspace.resolve(filename)


@pytest.mark.parametrize("filename", ["/etc/passwd.md", "/tmp/evil.md", "C:/evil.md"])
def test_absolute_paths_are_rejected(workspace, filename):
    with pytest.raises(UnsafePathError):
        workspace.resolve(filename)


@pytest.mark.parametrize(
    "filename,reason",
    [
        (".ssh_config.md", "hidden"),
        ("payload.sh", "extension"),
        ("a/b/c/d/e/f.md", "too deep"),
        ("chapter\x00.md", "control character"),
        ("", "empty"),
        ("   ", "blank"),
        ("x" * 300 + ".md", "too long"),
    ],
)
def test_unsafe_names_are_rejected(workspace, filename, reason):
    with pytest.raises(UnsafePathError):
        workspace.resolve(filename)


def test_valid_paths_resolve_inside_the_project(workspace):
    resolved = workspace.resolve("chapters/chapter_01.md")
    assert workspace.project_dir.resolve() in resolved.parents


def test_normalize_filename_appends_markdown():
    assert normalize_filename("chapter_01") == "chapter_01.md"
    assert normalize_filename("chapter_01.md") == "chapter_01.md"
    assert normalize_filename("notes.txt") == "notes.txt"


# --- project lifecycle (B-03) -----------------------------------------------


def test_file_operations_require_a_project(empty_workspace):
    assert not empty_workspace.is_ready
    with pytest.raises(NoProjectError):
        empty_workspace.write("a.md", "text")


def test_create_project_sanitizes_and_activates(empty_workspace, output_root):
    path, existed = empty_workspace.create_project("My Great Novel!")

    assert path == output_root / "My_Great_Novel"
    assert existed is False
    assert empty_workspace.is_ready


def test_create_project_reuses_an_existing_folder(empty_workspace):
    empty_workspace.create_project("Novel")
    _, existed = empty_workspace.create_project("Novel")
    assert existed is True


def test_create_project_cannot_escape_the_output_root(empty_workspace, output_root):
    path, _ = empty_workspace.create_project("../../etc")
    assert output_root.resolve() in path.resolve().parents


def test_two_workspaces_do_not_share_state(output_root):
    """The regression that made a web server impossible: a module level global."""
    first, second = Workspace(output_root), Workspace(output_root)
    first.create_project("novel_a")
    second.create_project("novel_b")

    first.write("a.md", "from A")
    second.write("b.md", "from B")

    assert [info.path for info in first.list_files()] == ["a.md"]
    assert [info.path for info in second.list_files()] == ["b.md"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("My Great Novel", "My_Great_Novel"),
        ("  spaced  ", "spaced"),
        ("weird!@#chars", "weirdchars"),
        ("../escape", "escape"),
        ("", "untitled_project"),
        ("!!!", "untitled_project"),
    ],
)
def test_sanitize_folder_name(raw, expected):
    assert sanitize_folder_name(raw) == expected


# --- file operations --------------------------------------------------------


def test_write_create_read_roundtrip(workspace):
    info = workspace.write("chapter_01.md", "Once upon a time", "create")

    assert info.path == "chapter_01.md"
    assert info.words == 4
    assert workspace.read("chapter_01.md") == "Once upon a time"


def test_create_twice_fails(workspace):
    workspace.write("a.md", "first", "create")
    with pytest.raises(WorkspaceError):
        workspace.write("a.md", "second", "create")
    assert workspace.read("a.md") == "first"


def test_append_requires_an_existing_file(workspace):
    """B-13: appending to a typo used to silently create a second file."""
    with pytest.raises(WorkspaceError):
        workspace.write("chapter_99.md", "text", "append")
    assert not workspace.exists("chapter_99.md")


def test_append_extends_an_existing_file(workspace):
    workspace.write("a.md", "start", "create")
    workspace.write("a.md", " and end", "append")
    assert workspace.read("a.md") == "start and end"


def test_overwrite_replaces_content(workspace):
    workspace.write("a.md", "old", "create")
    workspace.write("a.md", "new", "overwrite")
    assert workspace.read("a.md") == "new"


def test_invalid_mode_is_rejected(workspace):
    with pytest.raises(WorkspaceError):
        workspace.write("a.md", "text", "delete")


def test_oversized_content_is_rejected(workspace):
    with pytest.raises(WorkspaceError):
        workspace.write("huge.md", "x" * (MAX_FILE_BYTES + 1), "create")
    assert not workspace.exists("huge.md")


def test_read_missing_file_raises(workspace):
    with pytest.raises(WorkspaceError):
        workspace.read("nope.md")


def test_read_truncates_long_files(workspace):
    workspace.write("long.md", "x" * 1000, "create")
    text = workspace.read("long.md", max_chars=100)
    assert text.startswith("x" * 100)
    assert "truncated" in text


def test_read_tail_returns_the_end(workspace):
    workspace.write("a.md", "start-middle-END", "create")
    assert workspace.read_tail("a.md", 3) == "END"


def test_list_files_reports_words_and_skips_hidden(workspace):
    workspace.write("a.md", "one two three", "create")
    workspace.write("chapters/b.md", "four five", "create")
    (workspace.project_dir / ".context_summary_x.md").write_text("hidden", encoding="utf-8")

    listing = workspace.list_files()

    assert [info.path for info in listing] == ["a.md", "chapters/b.md"]
    assert workspace.total_words() == 5


# --- patching ---------------------------------------------------------------


def test_apply_patch_replaces_unique_text(workspace):
    workspace.write("a.md", "The sky was green today.", "create")
    workspace.apply_patch("a.md", "green", "grey")
    assert workspace.read("a.md") == "The sky was grey today."


def test_apply_patch_rejects_ambiguous_matches(workspace):
    workspace.write("a.md", "one one", "create")
    with pytest.raises(WorkspaceError, match="appears 2 times"):
        workspace.apply_patch("a.md", "one", "two")


def test_apply_patch_rejects_missing_text(workspace):
    workspace.write("a.md", "content", "create")
    with pytest.raises(WorkspaceError, match="not found"):
        workspace.apply_patch("a.md", "absent", "x")


def test_snapshot_path_is_hidden_and_inside_the_project(workspace):
    path = workspace.snapshot_path("20250101_000000")
    assert path.name.startswith(".context_summary_")
    assert path.parent == workspace.project_dir
