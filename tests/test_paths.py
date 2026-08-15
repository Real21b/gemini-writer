"""Path safety tests (regression cover for B-02: writing outside the project)."""

import pytest

from tools.paths import UnsafePathError, normalize_filename, resolve_in_project


def test_simple_filename_resolves_inside_project(tmp_path):
    resolved = resolve_in_project(str(tmp_path), "chapter_01.md")
    assert resolved == (tmp_path / "chapter_01.md").resolve()


def test_subdirectories_are_allowed(tmp_path):
    resolved = resolve_in_project(str(tmp_path), "chapters/chapter_01.md")
    assert resolved.parent.name == "chapters"
    assert tmp_path.resolve() in resolved.parents


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
def test_traversal_is_rejected(tmp_path, filename):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), filename)


@pytest.mark.parametrize("filename", ["/etc/passwd.md", "/tmp/evil.md", "C:/evil.md"])
def test_absolute_paths_are_rejected(tmp_path, filename):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), filename)


def test_hidden_files_are_rejected(tmp_path):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), ".ssh_config.md")


def test_disallowed_extension_is_rejected(tmp_path):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), "payload.sh")


def test_deep_nesting_is_rejected(tmp_path):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), "a/b/c/d/e/f/g.md")


def test_control_characters_are_rejected(tmp_path):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), "chapter\x00.md")


@pytest.mark.parametrize("filename", ["", "   ", "/", None])
def test_empty_names_are_rejected(tmp_path, filename):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), filename)


def test_overlong_name_is_rejected(tmp_path):
    with pytest.raises(UnsafePathError):
        resolve_in_project(str(tmp_path), "x" * 300 + ".md")


def test_normalize_filename_appends_markdown():
    assert normalize_filename("chapter_01") == "chapter_01.md"
    assert normalize_filename("chapter_01.md") == "chapter_01.md"
    assert normalize_filename("notes.txt") == "notes.txt"
