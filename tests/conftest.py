"""Shared test fixtures."""

from types import SimpleNamespace

import pytest

from tools import project as project_module


@pytest.fixture(autouse=True)
def reset_active_project():
    """Keep the module-level project folder from leaking between tests."""
    original = project_module.get_active_project_folder()
    yield
    project_module.set_active_project_folder(original)


@pytest.fixture
def active_project(tmp_path):
    """Point the tools at a throwaway project folder."""
    folder = tmp_path / "project"
    folder.mkdir()
    project_module.set_active_project_folder(str(folder))
    return folder


class FakeModels:
    """Stands in for client.models with a scripted response."""

    def __init__(self, text="SUMMARY TEXT", error=None):
        self.text = text
        self.error = error
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append({"model": model, "contents": contents})
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


class FakeClient:
    """Minimal stand-in for genai.Client."""

    def __init__(self, text="SUMMARY TEXT", error=None):
        self.models = FakeModels(text=text, error=error)


@pytest.fixture
def fake_client():
    return FakeClient()
