"""Snapshot and compression behaviour (regression cover for B-01)."""

from pathlib import Path

from tests.conftest import FakeClient
from tools.compression import compress_context_impl, snapshot_context


def _history(n=8):
    """A system message followed by n alternating turns."""
    messages = [{"role": "system", "content": "system prompt"}]
    for i in range(n):
        role = "user" if i % 2 == 0 else "model"
        messages.append({"role": role, "content": f"message {i}"})
    return messages


def _summary_files(folder: Path):
    return sorted(folder.glob(".context_summary_*.md"))


def test_snapshot_writes_a_recovery_file(active_project, fake_client):
    result = snapshot_context(_history(), fake_client, "test-model")

    assert result["summary_file"] is not None
    files = _summary_files(active_project)
    assert len(files) == 1
    assert "SUMMARY TEXT" in files[0].read_text(encoding="utf-8")


def test_snapshot_summarizes_every_message_not_just_the_old_ones(active_project, fake_client):
    """B-01: backups used to be routed through compress() and wrote nothing."""
    messages = _history(6)
    result = snapshot_context(messages, fake_client, "test-model")

    assert result["messages_summarized"] == 6
    sent = fake_client.models.calls[0]["contents"][0].parts[0].text
    assert "message 0" in sent and "message 5" in sent


def test_snapshot_with_too_little_history_writes_nothing(active_project, fake_client):
    result = snapshot_context([{"role": "system", "content": "s"}], fake_client, "test-model")

    assert result["summary_file"] is None
    assert _summary_files(active_project) == []


def test_snapshot_reports_api_errors_without_raising(active_project):
    client = FakeClient(error=RuntimeError("network down"))
    result = snapshot_context(_history(), client, "test-model")

    assert result["summary_file"] is None
    assert "network down" in result["message"]


def test_snapshot_skips_empty_summaries(active_project):
    client = FakeClient(text="   ")
    result = snapshot_context(_history(), client, "test-model")

    assert result["summary_file"] is None
    assert _summary_files(active_project) == []


def test_compression_clamps_oversized_keep_recent(active_project, fake_client):
    """keep_recent >= history used to disable compression entirely."""
    messages = _history(8)
    result = compress_context_impl(messages, fake_client, "test-model", keep_recent=len(messages))

    assert result["summary_file"] is not None
    assert result["messages_compressed"] >= 1
    assert len(result["compressed_messages"]) < len(messages)


def test_compression_keeps_system_and_recent_messages(active_project, fake_client):
    messages = _history(10)
    result = compress_context_impl(messages, fake_client, "test-model", keep_recent=3)

    compressed = result["compressed_messages"]
    assert compressed[0]["role"] == "system"
    assert "[CONTEXT SUMMARY" in compressed[1]["content"]
    assert [m["content"] for m in compressed[-3:]] == ["message 7", "message 8", "message 9"]


def test_compression_without_system_message(active_project, fake_client):
    messages = [{"role": "user", "content": f"m{i}"} for i in range(6)]
    result = compress_context_impl(messages, fake_client, "test-model", keep_recent=2)

    assert result["compressed_messages"][0]["role"] == "user"
    assert "[CONTEXT SUMMARY" in result["compressed_messages"][0]["content"]


def test_compression_returns_original_on_error(active_project):
    client = FakeClient(error=RuntimeError("boom"))
    messages = _history(8)
    result = compress_context_impl(messages, client, "test-model", keep_recent=3)

    assert result["compressed_messages"] == messages
    assert "boom" in result["message"]


def test_compression_noop_for_short_history(active_project, fake_client):
    messages = _history(2)
    result = compress_context_impl(messages, fake_client, "test-model", keep_recent=10)

    assert result["compressed_messages"] == messages
    assert result["summary_file"] is None
