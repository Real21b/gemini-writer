"""Project folder creation and name sanitization."""

import pytest

from tools import project as project_module
from tools.project import (
    create_project_impl,
    get_active_project_folder,
    get_output_dir,
    sanitize_folder_name,
)


@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    target = tmp_path / "output"
    monkeypatch.setenv("GEMINI_WRITER_OUTPUT_DIR", str(target))
    return target


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("My Great Novel", "My_Great_Novel"),
        ("  spaced  ", "spaced"),
        ("weird!@#chars", "weirdchars"),
        ("../escape", "escape"),
        ("-leading-and-trailing-", "leading-and-trailing"),
        ("", "untitled_project"),
        ("!!!", "untitled_project"),
    ],
)
def test_sanitize_folder_name(raw, expected):
    assert sanitize_folder_name(raw) == expected


def test_create_project_creates_and_activates_folder(output_dir):
    result = create_project_impl("My Great Novel")

    created = output_dir / "My_Great_Novel"
    assert created.is_dir()
    assert get_active_project_folder() == str(created)
    assert "Successfully created" in result


def test_create_project_reuses_existing_folder(output_dir):
    create_project_impl("Novel")
    project_module.set_active_project_folder(None)

    result = create_project_impl("Novel")

    assert "already exists" in result
    assert get_active_project_folder() == str(output_dir / "Novel")


def test_create_project_cannot_escape_the_output_dir(output_dir):
    create_project_impl("../../etc")

    active = get_active_project_folder()
    assert active.startswith(str(output_dir))


def test_create_project_reports_errors(output_dir, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(project_module.os, "makedirs", boom)
    result = create_project_impl("Novel")

    assert result.startswith("Error creating")


def test_output_dir_defaults_to_repo_output(monkeypatch):
    monkeypatch.delenv("GEMINI_WRITER_OUTPUT_DIR", raising=False)
    assert get_output_dir().endswith("output")
