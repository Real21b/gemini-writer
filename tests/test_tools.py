"""
Tests for the project management tools.
"""

import os
import shutil
import tempfile

import pytest

from tools.project import sanitize_folder_name, create_project_impl, set_active_project_folder, get_active_project_folder
from tools.writer import write_file_impl


# ── sanitize_folder_name ──────────────────────────────────────────────


class TestSanitizeFolderName:
    def test_spaces_replaced_with_underscores(self):
        assert sanitize_folder_name("my project") == "my_project"

    def test_special_characters_removed(self):
        assert sanitize_folder_name("hello@world!") == "helloworld"

    def test_leading_trailing_stripped(self):
        assert sanitize_folder_name("--name--") == "name"

    def test_empty_string_returns_default(self):
        assert sanitize_folder_name("") == "untitled_project"

    def test_only_special_chars_returns_default(self):
        assert sanitize_folder_name("@#$%") == "untitled_project"


# ── create_project_impl ──────────────────────────────────────────────


class TestCreateProject:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Monkey-patch output dir to use tmp
        import tools.project as proj_mod
        self._orig_file = proj_mod.__file__
        # We override by setting active folder directly for isolation
        set_active_project_folder(None)

    def teardown_method(self):
        set_active_project_folder(None)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_project_sets_active_folder(self):
        result = create_project_impl("Test Project")
        assert "Successfully created" in result or "already exists" in result
        assert get_active_project_folder() is not None


# ── write_file_impl ──────────────────────────────────────────────────


class TestWriteFile:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        set_active_project_folder(self.tmpdir)

    def teardown_method(self):
        set_active_project_folder(None)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_new_file(self):
        result = write_file_impl("chapter_01.md", "# Chapter 1\n\nHello world.", "create")
        assert "Successfully created" in result
        fpath = os.path.join(self.tmpdir, "chapter_01.md")
        assert os.path.isfile(fpath)
        with open(fpath) as f:
            assert f.read() == "# Chapter 1\n\nHello world."

    def test_create_file_adds_md_extension(self):
        result = write_file_impl("chapter_02", "content", "create")
        assert "Successfully created" in result
        assert os.path.isfile(os.path.join(self.tmpdir, "chapter_02.md"))

    def test_create_fails_if_exists(self):
        write_file_impl("dup.md", "first", "create")
        result = write_file_impl("dup.md", "second", "create")
        assert "already exists" in result

    def test_append_to_file(self):
        write_file_impl("story.md", "Part 1. ", "create")
        write_file_impl("story.md", "Part 2.", "append")
        with open(os.path.join(self.tmpdir, "story.md")) as f:
            assert f.read() == "Part 1. Part 2."

    def test_overwrite_file(self):
        write_file_impl("draft.md", "old", "create")
        write_file_impl("draft.md", "new", "overwrite")
        with open(os.path.join(self.tmpdir, "draft.md")) as f:
            assert f.read() == "new"

    def test_no_active_project(self):
        set_active_project_folder(None)
        result = write_file_impl("x.md", "y", "create")
        assert "No active project" in result
