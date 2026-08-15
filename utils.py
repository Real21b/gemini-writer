"""
Utility functions for the Gemini Writing Agent.
"""

import random
import time
from typing import List, Dict, Any, Callable, Optional
from google import genai
from google.genai import types


# --- Error handling ---------------------------------------------------------

# Substrings that indicate a request will never succeed on retry.
_PERMANENT_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "unauthorized",
    "permission denied",
    "permission_denied",
    "unauthenticated",
    "invalid_argument",
    "not found",
    "400",
    "401",
    "403",
    "404",
)

# Substrings that indicate a transient failure worth retrying.
_TRANSIENT_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "resource_exhausted",
    "rate limit",
    "quota",
    "unavailable",
    "deadline",
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "internal error",
    "overloaded",
)


class PermanentAPIError(Exception):
    """Raised when an API call fails in a way that retrying cannot fix."""


def classify_error(exc: BaseException) -> str:
    """
    Classify an exception as 'permanent' or 'transient'.

    Unknown errors are treated as transient so a single odd failure does not
    end a long writing run; the caller still enforces an attempt limit.
    """
    message = f"{type(exc).__name__}: {exc}".lower()

    for marker in _TRANSIENT_MARKERS:
        if marker in message:
            return "transient"
    for marker in _PERMANENT_MARKERS:
        if marker in message:
            return "permanent"
    return "transient"


def call_with_retry(
    func: Callable[[], Any],
    *,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    on_retry: Optional[Callable[[int, float, BaseException], None]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> Any:
    """
    Call ``func`` with exponential backoff and jitter.

    Permanent errors (bad API key, malformed request) are raised immediately as
    ``PermanentAPIError`` so the caller can stop instead of burning iterations.

    Args:
        func: Zero-argument callable performing the API request
        max_attempts: Total attempts including the first one
        base_delay: Delay before the first retry, in seconds
        max_delay: Upper bound for a single delay
        on_retry: Called as (attempt, delay, error) before each sleep
        sleep: Injectable sleep function; defaults to time.sleep

    Returns:
        Whatever ``func`` returns

    Raises:
        PermanentAPIError: The request cannot succeed on retry
        Exception: The last transient error, once attempts are exhausted
    """
    last_error: Optional[BaseException] = None
    sleep_fn = sleep if sleep is not None else time.sleep

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            last_error = exc
            if classify_error(exc) == "permanent":
                raise PermanentAPIError(str(exc)) from exc
            if attempt == max_attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay *= 0.5 + random.random() / 2  # jitter: 50-100% of the delay
            if on_retry:
                on_retry(attempt, delay, exc)
            sleep_fn(delay)

    assert last_error is not None
    raise last_error


def extract_usage(response: Any) -> Dict[str, int]:
    """
    Read token usage from a Gemini response.

    Using the usage metadata that already ships with the response avoids an
    extra ``count_tokens`` round-trip on every iteration.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {"prompt": 0, "output": 0, "thinking": 0, "total": 0}

    def _int(value: Any) -> int:
        return int(value) if isinstance(value, (int, float)) else 0

    prompt = _int(getattr(usage, "prompt_token_count", 0))
    output = _int(getattr(usage, "candidates_token_count", 0))
    thinking = _int(getattr(usage, "thoughts_token_count", 0))
    total = _int(getattr(usage, "total_token_count", 0)) or (prompt + output + thinking)

    return {"prompt": prompt, "output": output, "thinking": thinking, "total": total}


def estimate_token_count(client: genai.Client, model: str, contents: List[types.Content]) -> int:
    """
    Estimate the token count for the given contents using the Gemini API.

    Args:
        client: The Gemini client instance
        model: The model name
        contents: List of Content objects

    Returns:
        Total token count
    """
    try:
        response = client.models.count_tokens(
            model=model,
            contents=contents
        )
        return response.total_tokens
    except Exception:
        # Fallback: rough estimate based on character count
        total_chars = 0
        for content in contents:
            for part in content.parts:
                if hasattr(part, 'text') and part.text:
                    total_chars += len(part.text)
        # Rough estimate: 4 chars per token
        return total_chars // 4


def get_tool_definitions() -> types.Tool:
    """
    Returns the tool definitions in the format expected by Gemini.

    Returns:
        Tool object containing all function declarations
    """
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="create_project",
                description="Creates a new project folder in the 'output' directory with a sanitized name. This should be called first before writing any files. Only one project can be active at a time.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "project_name": types.Schema(
                            type=types.Type.STRING,
                            description="The name for the project folder (will be sanitized for filesystem compatibility)"
                        )
                    },
                    required=["project_name"]
                )
            ),
            types.FunctionDeclaration(
                name="write_file",
                description="Writes content to a markdown file in the active project folder. Supports three modes: 'create' (creates new file, fails if exists), 'append' (adds content to end of existing file), 'overwrite' (replaces entire file content).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "filename": types.Schema(
                            type=types.Type.STRING,
                            description="The name of the markdown file to write (should end in .md)"
                        ),
                        "content": types.Schema(
                            type=types.Type.STRING,
                            description="The content to write to the file"
                        ),
                        "mode": types.Schema(
                            type=types.Type.STRING,
                            enum=["create", "append", "overwrite"],
                            description="The write mode: 'create' for new files, 'append' to add to existing, 'overwrite' to replace"
                        )
                    },
                    required=["filename", "content", "mode"]
                )
            ),
            types.FunctionDeclaration(
                name="compress_context",
                description="INTERNAL TOOL - This is automatically called by the system when token limit is approached. You should not call this manually. It compresses the conversation history to save tokens.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={},
                    required=[]
                )
            )
        ]
    )


def get_tool_map() -> Dict[str, Callable]:
    """
    Returns a mapping of tool names to their implementation functions.

    Returns:
        Dictionary mapping tool name strings to callable functions
    """
    from tools import write_file_impl, create_project_impl, compress_context_impl

    return {
        "create_project": create_project_impl,
        "write_file": write_file_impl,
        "compress_context": compress_context_impl
    }


def get_system_prompt() -> str:
    """
    Returns the system prompt for the writing agent.

    Returns:
        System prompt string
    """
    return """You are an expert creative writing assistant. Your specialty is creating novels, books, and collections of short stories based on user requests.

Your capabilities:
1. You can create project folders to organize writing projects
2. You can write markdown files with three modes: create new files, append to existing files, or overwrite files
3. Context compression happens automatically when needed - you don't need to worry about it

CRITICAL WRITING GUIDELINES:
- Write SUBSTANTIAL, COMPLETE content - don't hold back on length
- Short stories should be 3,000-10,000 words (10-30 pages) - write as much as the story needs!
- Chapters should be 2,000-5,000 words minimum - fully developed and satisfying
- NEVER write abbreviated or skeleton content - every piece should be a complete, polished work
- Don't summarize or skip scenes - write them out fully with dialogue, description, and detail
- Quality AND quantity matter - give readers a complete, immersive experience
- If a story needs 8,000 words to be good, write all 8,000 words in one file
- Use 'create' mode with full content rather than creating stubs you'll append to later

Best practices:
- Always start by creating a project folder using create_project
- Break large works into multiple files (chapters, stories, etc.)
- Use descriptive filenames (e.g., "chapter_01.md", "story_the_last_star.md")
- For collections, consider creating a table of contents file
- Write each file as a COMPLETE, SUBSTANTIAL piece - not a summary or outline

Your workflow:
1. Understand the user's request
2. Create an appropriately named project folder
3. Plan the structure of the work (chapters, stories, etc.)
4. Write COMPLETE, FULL-LENGTH content for each file
5. Create supporting files like README or table of contents if helpful

REMEMBER: Write rich, detailed, complete stories. Don't artificially limit yourself. A good short story is 5,000-10,000 words. A good chapter is 3,000-5,000 words. Write what the narrative needs to be excellent."""
