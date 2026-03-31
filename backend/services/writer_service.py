"""
Writer service – runs the Gemini agentic loop and streams events over a callback.

This module encapsulates the core AI writing logic so that both the CLI
(writer.py) and the FastAPI WebSocket endpoint can reuse it.
"""

import json
import os
from typing import Any, Callable, Awaitable

from google import genai
from google.genai import types

from backend.core.config import settings
from tools.project import create_project_impl, get_active_project_folder, set_active_project_folder
from tools.writer import write_file_impl
from tools.compression import compress_context_impl
from utils import get_system_prompt, get_tool_definitions


# Type alias for the event callback used by the WebSocket layer.
EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


async def run_writer(
    prompt: str,
    project_id: str,
    on_event: EventCallback,
    *,
    is_recovery: bool = False,
) -> None:
    """
    Execute the agentic writing loop.

    Parameters
    ----------
    prompt : str
        The user's writing prompt (or recovered context).
    project_id : str
        Database project id – passed through events so the frontend can track it.
    on_event : EventCallback
        ``async def callback(event_type: str, data: dict)`` invoked for every
        notable event (thinking, content, tool_call, progress, done, error).
    is_recovery : bool
        When *True* the prompt is treated as recovered context.
    """

    api_key = settings.gemini_api_key
    if not api_key:
        await on_event("error", {"message": "GEMINI_API_KEY is not configured."})
        return

    client = genai.Client(api_key=api_key)
    await on_event("status", {"message": "Gemini client initialized."})

    # ── Prepare initial contents ─────────────────────────────────────
    contents: list[types.Content] = []

    if is_recovery:
        initial_message = (
            f"[RECOVERED CONTEXT]\n\n{prompt}\n\n[END RECOVERED CONTEXT]\n\n"
            "Please continue the work from where we left off."
        )
    else:
        initial_message = prompt

    contents.append(
        types.Content(
            role="user", parts=[types.Part.from_text(text=initial_message)]
        )
    )

    tools = get_tool_definitions()
    tool_map: dict[str, Callable[..., Any]] = {
        "create_project": create_project_impl,
        "write_file": write_file_impl,
        "compress_context": compress_context_impl,
    }
    system_instruction = get_system_prompt()

    max_iterations = settings.max_iterations
    token_limit = settings.token_limit
    compression_threshold = settings.compression_threshold
    model_name = settings.model_name
    backup_interval = settings.backup_interval

    await on_event(
        "config",
        {
            "model": model_name,
            "max_iterations": max_iterations,
            "token_limit": token_limit,
        },
    )

    # ── Main agentic loop ────────────────────────────────────────────
    for iteration in range(1, max_iterations + 1):
        # -- Token counting -------------------------------------------------
        token_count = 0
        try:
            resp = client.models.count_tokens(model=model_name, contents=contents)
            token_count = resp.total_tokens
        except Exception:
            total_chars = sum(
                len(p.text)
                for c in contents
                for p in c.parts
                if hasattr(p, "text") and p.text
            )
            token_count = total_chars // 4

        await on_event(
            "progress",
            {
                "iteration": iteration,
                "max_iterations": max_iterations,
                "tokens": token_count,
                "token_limit": token_limit,
                "project_id": project_id,
            },
        )

        # -- Compression if needed ------------------------------------------
        if token_count >= compression_threshold:
            await on_event("status", {"message": "Compressing context…"})
            simple_msgs = _contents_to_simple(contents, system_instruction)
            result = compress_context_impl(
                messages=simple_msgs,
                client=client,
                model=model_name,
                keep_recent=10,
            )
            if "compressed_messages" in result:
                contents = _simple_to_contents(result["compressed_messages"])
                await on_event(
                    "status",
                    {"message": f"Context compressed – saved ~{result.get('tokens_saved', 0):,} tokens."},
                )

        # -- Auto-backup ----------------------------------------------------
        if iteration % backup_interval == 0:
            try:
                simple_msgs = _contents_to_simple(contents, system_instruction)
                compress_context_impl(
                    messages=simple_msgs,
                    client=client,
                    model=model_name,
                    keep_recent=len(simple_msgs),
                )
            except Exception:
                pass

        # -- Generate content -----------------------------------------------
        generate_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
            tools=[tools],
            temperature=1.0,
        )

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=generate_config,
            )
        except Exception as exc:
            await on_event("error", {"message": str(exc), "iteration": iteration})
            continue

        # -- Parse response -------------------------------------------------
        thinking_text = ""
        content_text = ""
        function_calls_list: list[dict[str, Any]] = []
        model_content = None

        if response.candidates and response.candidates[0].content:
            model_content = response.candidates[0].content
            for part in model_content.parts:
                if hasattr(part, "thought") and part.thought:
                    if hasattr(part, "text") and part.text:
                        thinking_text += part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    function_calls_list.append(
                        {"name": fc.name, "args": dict(fc.args) if fc.args else {}}
                    )
                elif hasattr(part, "text") and part.text:
                    content_text += part.text

        if thinking_text:
            await on_event("thinking", {"text": thinking_text, "iteration": iteration})
        if content_text:
            await on_event("content", {"text": content_text, "iteration": iteration})

        if model_content:
            contents.append(model_content)

        # -- No tool calls → task complete ----------------------------------
        if not function_calls_list:
            await on_event(
                "done",
                {
                    "iteration": iteration,
                    "project_id": project_id,
                    "message": f"Completed in {iteration} iteration(s).",
                },
            )
            return

        # -- Handle tool calls ----------------------------------------------
        function_response_parts = []
        for fc in function_calls_list:
            func_name = fc["name"]
            args = fc["args"]
            await on_event(
                "tool_call",
                {"name": func_name, "args": args, "iteration": iteration},
            )

            tool_func = tool_map.get(func_name)
            if not tool_func:
                result_str = f"Error: Unknown tool '{func_name}'"
            elif func_name == "compress_context":
                simple_msgs = _contents_to_simple(contents, system_instruction)
                result_data = compress_context_impl(
                    messages=simple_msgs,
                    client=client,
                    model=model_name,
                    keep_recent=10,
                )
                result_str = result_data.get("message", "Compression completed")
            else:
                result_str = str(tool_func(**args))

            await on_event(
                "tool_result",
                {"name": func_name, "result": result_str[:500], "iteration": iteration},
            )

            function_response_parts.append(
                types.Part.from_function_response(
                    name=func_name, response={"result": result_str}
                )
            )

        contents.append(
            types.Content(role="user", parts=function_response_parts)
        )

    # Max iterations reached
    await on_event(
        "done",
        {
            "iteration": max_iterations,
            "project_id": project_id,
            "message": f"Reached maximum of {max_iterations} iterations.",
        },
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _contents_to_simple(
    contents: list[types.Content], system_instruction: str
) -> list[dict[str, str]]:
    """Convert Content objects to simple dicts for compression."""
    msgs: list[dict[str, str]] = [{"role": "system", "content": system_instruction}]
    for content in contents:
        text_parts = [
            p.text for p in content.parts if hasattr(p, "text") and p.text
        ]
        if text_parts:
            msgs.append({"role": content.role, "content": " ".join(text_parts)})
    return msgs


def _simple_to_contents(
    messages: list[dict[str, str]],
) -> list[types.Content]:
    """Convert simple message dicts back to Content objects."""
    contents: list[types.Content] = []
    for msg in messages:
        if msg.get("role") == "system":
            continue
        role = "model" if msg.get("role") in ("assistant", "model") else "user"
        if msg.get("content"):
            contents.append(
                types.Content(
                    role=role, parts=[types.Part.from_text(text=msg["content"])]
                )
            )
    return contents
