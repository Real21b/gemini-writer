"""
Context compression and snapshot tools.

Two distinct operations live here:

* ``snapshot_context`` - summarize the *whole* conversation and write it to a
  recovery file. Used for periodic backups, Ctrl+C and max-iteration exits.
* ``compress_context_impl`` - shrink the working context by summarizing older
  messages while keeping the most recent turns verbatim.

They used to be the same function, which meant every backup call hit the
"not enough messages to compress" early return and silently wrote nothing.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from .project import get_active_project_folder


# A summary is only meaningful once there is an actual exchange to summarize.
MIN_MESSAGES_TO_SUMMARIZE = 2

SUMMARY_PROMPT = """Please provide a comprehensive summary of the conversation history below. Include:
1. The main task or goal discussed
2. Key decisions made
3. Files created and their purposes
4. Progress made so far
5. Any important context for continuing the work

Conversation history to summarize:
"""


def _split_system_message(messages: List[Any]) -> tuple[Optional[Any], List[Any]]:
    """Separate a leading system message from the rest of the history."""
    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        return messages[0], list(messages[1:])
    return None, list(messages)


def _build_conversation_text(messages: List[Any]) -> str:
    """Render a message list as plain text for the summarizer."""
    conversation_text = ""

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role in ("model", "assistant"):
            thinking = msg.get("thinking")
            if thinking:
                conversation_text += f"\n[Assistant Thinking]: {thinking[:500]}...\n"

            func_calls = msg.get("function_calls")
            if func_calls:
                tool_calls_info = [
                    f"{fc.get('name', 'unknown')}({fc.get('args', {})})" for fc in func_calls
                ]
                conversation_text += f"\n[Assistant Function Calls]: {', '.join(tool_calls_info)}\n"

            if content:
                conversation_text += f"\n[Assistant]: {content}\n"

        elif role == "tool":
            tool_name = msg.get("name", "unknown_tool")
            conversation_text += f"\n[Tool Result - {tool_name}]: {str(content)[:200]}...\n"

        elif role == "user":
            conversation_text += f"\n[User]: {content}\n"

    return conversation_text


def _summarize(client: genai.Client, model: str, conversation_text: str) -> str:
    """Ask the model for a summary of the given conversation text."""
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=SUMMARY_PROMPT + conversation_text)],
        )
    ]

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=4096),
    )
    return response.text or ""


def _summary_file_path() -> str:
    """Build a timestamped summary path inside the active project folder."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_folder = get_active_project_folder()
    if project_folder:
        return os.path.join(project_folder, f".context_summary_{timestamp}.md")
    return f".context_summary_{timestamp}.md"


def _write_summary_file(summary: str, summarized: int, retained: int) -> str:
    """Persist a summary to disk and return the path it was written to."""
    summary_file = _summary_file_path()
    parent = os.path.dirname(summary_file)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(summary_file, "w", encoding="utf-8") as f:
        f.write("# Context Summary\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Messages Summarized:** {summarized}\n\n")
        f.write(f"**Messages Retained:** {retained}\n\n")
        f.write("---\n\n")
        f.write(summary)

    return summary_file


def snapshot_context(
    messages: List[Any],
    client: genai.Client,
    model: str,
) -> Dict[str, Any]:
    """
    Summarize the entire conversation and write it to a recovery file.

    Unlike ``compress_context_impl`` this never drops anything from the live
    context - it only produces the file that ``--recover`` consumes.

    Returns:
        Dictionary with ``summary_file`` (path or None) and a human readable
        ``message``.
    """
    _, body = _split_system_message(messages)

    if len(body) < MIN_MESSAGES_TO_SUMMARIZE:
        return {
            "summary_file": None,
            "messages_summarized": 0,
            "message": "Not enough conversation history to snapshot yet.",
        }

    try:
        summary = _summarize(client, model, _build_conversation_text(body))
    except Exception as e:  # noqa: BLE001 - surfaced to the caller as a message
        return {
            "summary_file": None,
            "messages_summarized": 0,
            "message": f"Error creating snapshot: {e}",
        }

    if not summary.strip():
        return {
            "summary_file": None,
            "messages_summarized": 0,
            "message": "Snapshot skipped: the model returned an empty summary.",
        }

    try:
        summary_file = _write_summary_file(summary, summarized=len(body), retained=0)
    except OSError as e:
        return {
            "summary_file": None,
            "messages_summarized": len(body),
            "message": f"Error saving snapshot: {e}",
        }

    return {
        "summary_file": summary_file,
        "messages_summarized": len(body),
        "message": (
            f"Snapshot of {len(body)} messages saved to {os.path.basename(summary_file)}."
        ),
    }


def compress_context_impl(
    messages: List[Any],
    client: genai.Client,
    model: str,
    keep_recent: int = 10,
) -> Dict[str, Any]:
    """
    Compresses the conversation context by summarizing older messages.

    Args:
        messages: The full message history (optionally starting with a system message)
        client: The Gemini client instance
        model: The model to use for summarization
        keep_recent: Number of recent messages to keep verbatim. Values larger
            than the history are clamped so that there is always something left
            to compress.

    Returns:
        Dictionary containing compressed_messages, summary_file, tokens_saved
        and a human readable message.
    """
    system_message, body = _split_system_message(messages)

    if len(body) <= MIN_MESSAGES_TO_SUMMARIZE:
        return {
            "compressed_messages": messages,
            "summary_file": None,
            "tokens_saved": 0,
            "message": "Not enough messages to compress.",
        }

    # Clamp: a keep_recent that covers the whole history would compress nothing.
    # Small explicit values are honoured exactly; oversized ones fall back to
    # keeping the most recent half.
    keep_recent = int(keep_recent)
    if keep_recent >= len(body):
        keep_recent = max(1, len(body) // 2)
    keep_recent = max(1, keep_recent)

    messages_to_compress = body[:-keep_recent]
    recent_messages = body[-keep_recent:]

    try:
        summary = _summarize(client, model, _build_conversation_text(messages_to_compress))
    except Exception as e:  # noqa: BLE001 - compression must never crash the run
        return {
            "compressed_messages": messages,
            "summary_file": None,
            "tokens_saved": 0,
            "message": f"Error during compression: {e}",
        }

    if not summary.strip():
        return {
            "compressed_messages": messages,
            "summary_file": None,
            "tokens_saved": 0,
            "message": "Compression skipped: the model returned an empty summary.",
        }

    try:
        summary_file = _write_summary_file(
            summary, summarized=len(messages_to_compress), retained=keep_recent
        )
    except OSError as e:
        summary_file = None
        save_note = f" (summary could not be saved: {e})"
    else:
        save_note = ""

    compressed_messages: List[Any] = []
    if system_message:
        compressed_messages.append(system_message)

    compressed_messages.append(
        {
            "role": "user",
            "content": (
                "[CONTEXT SUMMARY - Previous conversation compressed]\n\n"
                f"{summary}\n\n"
                "[END CONTEXT SUMMARY - Continuing from here...]"
            ),
        }
    )
    compressed_messages.extend(recent_messages)

    original_length = sum(len(str(m)) for m in messages_to_compress)
    estimated_tokens_saved = max(0, (original_length - len(summary)) // 4)

    where = os.path.basename(summary_file) if summary_file else "memory only"
    return {
        "compressed_messages": compressed_messages,
        "summary_file": summary_file,
        "tokens_saved": estimated_tokens_saved,
        "messages_compressed": len(messages_to_compress),
        "messages_retained": keep_recent,
        "message": (
            f"Successfully compressed {len(messages_to_compress)} messages. "
            f"Summary saved to {where}.{save_note}"
        ),
    }
