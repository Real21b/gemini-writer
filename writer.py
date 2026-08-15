#!/usr/bin/env python3
"""
Gemini Writing Agent - An autonomous agent for creative writing tasks.

This agent uses the Gemini 3 Flash model to create novels, books,
and short story collections based on user prompts.
"""

import os
import sys
import json
import argparse
from dotenv import load_dotenv
from google import genai
from google.genai import types
from typing import List, Dict, Any, Optional

# Load environment variables from .env file
load_dotenv()

from utils import (
    PermanentAPIError,
    call_with_retry,
    estimate_token_count,
    extract_usage,
    get_tool_definitions,
    get_tool_map,
    get_system_prompt,
)
from tools.compression import compress_context_impl, snapshot_context


# Constants
MAX_ITERATIONS = 300
TOKEN_LIMIT = 1000000  # Gemini has 1M context window
COMPRESSION_THRESHOLD = 900000  # Trigger compression at 90% of limit
MODEL_NAME = "gemini-3-flash-preview"
BACKUP_INTERVAL = 50  # Save backup summary every N iterations
MAX_CONSECUTIVE_ERRORS = 5  # Give up after this many failed iterations in a row
API_MAX_ATTEMPTS = 5  # Attempts per model call, with exponential backoff


def load_context_from_file(file_path: str) -> str:
    """
    Loads context from a summary file for recovery.

    Args:
        file_path: Path to the context summary file

    Returns:
        Content of the file as string
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"✓ Loaded context from: {file_path}\n")
        return content
    except OSError as e:
        print(f"✗ Error loading context file: {e}")
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    """Parses command line arguments."""
    parser = argparse.ArgumentParser(
        description="Gemini Writing Agent - Create novels, books, and short stories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fresh start with inline prompt
  python writer.py "Create a collection of sci-fi short stories"

  # Recovery mode from previous context
  python writer.py --recover output/my_project/.context_summary_20250107_143022.md
        """
    )

    parser.add_argument(
        'prompt',
        nargs='?',
        help='Your writing request (e.g., "Create a mystery novel")'
    )
    parser.add_argument(
        '--recover',
        type=str,
        help='Path to a context summary file to continue from'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print extra diagnostics (including a masked API key preview)'
    )

    return parser.parse_args()


def get_user_input(args: argparse.Namespace) -> tuple[str, bool]:
    """
    Resolves the writing request, either from arguments or interactively.

    Returns:
        Tuple of (prompt/context, is_recovery_mode)
    """
    # Check if recovery mode
    if args.recover:
        context = load_context_from_file(args.recover)
        return context, True

    # Check if prompt provided as argument
    if args.prompt:
        return args.prompt, False

    # Interactive prompt
    print("=" * 60)
    print("Gemini Writing Agent")
    print("=" * 60)
    print("\nEnter your writing request (or 'quit' to exit):")
    print("Example: Create a collection of 15 sci-fi short stories\n")

    prompt = input("> ").strip()

    if prompt.lower() in ['quit', 'exit', 'q']:
        print("Goodbye!")
        sys.exit(0)

    if not prompt:
        print("Error: Empty prompt. Please provide a writing request.")
        sys.exit(1)

    return prompt, False


MAX_ARG_CHARS = 120       # per tool argument in a snapshot
MAX_RESULT_CHARS = 200    # per tool result in a snapshot
MAX_THINKING_CHARS = 500  # per thinking block in a snapshot


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "..."


def _render_part(part: Any) -> Optional[str]:
    """Render a single response part as text for the summarizer."""
    function_call = getattr(part, 'function_call', None)
    if function_call:
        args = getattr(function_call, 'args', None) or {}
        rendered_args = ", ".join(
            f"{key}={_truncate(value, MAX_ARG_CHARS)}" for key, value in args.items()
        )
        return f"[Tool call] {function_call.name}({rendered_args})"

    function_response = getattr(part, 'function_response', None)
    if function_response:
        response = getattr(function_response, 'response', None) or {}
        result = response.get("result", response) if isinstance(response, dict) else response
        return f"[Tool result] {function_response.name}: {_truncate(result, MAX_RESULT_CHARS)}"

    text = getattr(part, 'text', None)
    if text:
        if getattr(part, 'thought', False):
            return f"[Thinking] {_truncate(text, MAX_THINKING_CHARS)}"
        return text

    return None


def to_simple_messages(
    contents: List[types.Content],
    system_instruction: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Flattens Gemini Content objects into the {role, content} dicts used by the
    summarizer.

    Tool calls and tool results are rendered as text: a recovery snapshot is
    only useful if it records which files were already written. Long arguments
    (a whole chapter, for instance) are truncated - the snapshot needs the
    decision, not the prose.

    This is a lossy view and is only used for producing summaries, never for
    feeding the model back its own history.
    """
    messages: List[Dict[str, str]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    for content in contents:
        rendered = [
            piece for piece in (_render_part(part) for part in content.parts or []) if piece
        ]
        if rendered:
            messages.append({"role": content.role, "content": "\n".join(rendered)})

    return messages


def save_snapshot(
    contents: List[types.Content],
    system_instruction: str,
    client: genai.Client,
    label: str,
) -> Optional[str]:
    """
    Writes a recovery snapshot of the conversation to disk.

    Returns:
        Path to the summary file, or None when nothing was written.
    """
    try:
        result = snapshot_context(
            messages=to_simple_messages(contents, system_instruction),
            client=client,
            model=MODEL_NAME,
        )
    except Exception as e:  # noqa: BLE001 - snapshots must never mask the real exit
        print(f"⚠️  {label} failed: {e}")
        return None

    summary_file = result.get("summary_file")
    if summary_file:
        print(f"✓ {label}: {os.path.basename(summary_file)}")
        return summary_file

    print(f"⚠️  {label} skipped: {result.get('message', 'unknown reason')}")
    return None


def print_recovery_hint(summary_file: Optional[str]) -> None:
    """Prints the exact command needed to resume from a snapshot."""
    if not summary_file:
        return
    print("\nTo resume, run:")
    print(f"  python writer.py --recover {summary_file}")


def compress_if_needed(
    contents: List[types.Content],
    system_instruction: str,
    client: genai.Client,
    token_count: int,
) -> tuple[List[types.Content], int]:
    """
    Compresses the conversation when it approaches the token limit.

    Returns:
        Tuple of (contents, token_count) - unchanged when no compression ran.
    """
    if token_count < COMPRESSION_THRESHOLD:
        return contents, token_count

    print("\n⚠️  Approaching token limit! Compressing context...")
    compression_result = compress_context_impl(
        messages=to_simple_messages(contents, system_instruction),
        client=client,
        model=MODEL_NAME,
        keep_recent=10,
    )

    if "compressed_messages" not in compression_result:
        print(f"⚠️  {compression_result.get('message', 'Compression failed')}")
        return contents, token_count

    new_contents: List[types.Content] = []
    for msg in compression_result["compressed_messages"]:
        if msg.get("role") == "system" or not msg.get("content"):
            continue
        role = "model" if msg.get("role") in ("assistant", "model") else "user"
        new_contents.append(types.Content(
            role=role,
            parts=[types.Part.from_text(text=msg["content"])]
        ))

    if not new_contents:
        print("⚠️  Compression produced no usable context; keeping the original.")
        return contents, token_count

    print(f"✓ {compression_result['message']}")
    print(f"✓ Estimated tokens saved: ~{compression_result.get('tokens_saved', 0):,}")

    # One count_tokens call here is worth it: it confirms compression worked.
    new_count = estimate_token_count(client, MODEL_NAME, new_contents)
    print(f"📊 New token count: {new_count:,}/{TOKEN_LIMIT:,}\n")
    return new_contents, new_count


def execute_tool(func_name: str, args: Dict[str, Any], tool_map: Dict[str, Any],
                 contents: List[types.Content], system_instruction: str,
                 client: genai.Client) -> str:
    """Runs a single tool call and returns its result as a string."""
    tool_func = tool_map.get(func_name)
    if not tool_func:
        return f"Error: Unknown tool '{func_name}'"

    # compress_context needs the conversation and the client, not model args.
    if func_name == "compress_context":
        result_data = compress_context_impl(
            messages=to_simple_messages(contents, system_instruction),
            client=client,
            model=MODEL_NAME,
            keep_recent=10,
        )
        return result_data.get("message", "Compression completed")

    try:
        return str(tool_func(**args))
    except TypeError as e:
        # Bad arguments from the model must not crash the run.
        return f"Error: Invalid arguments for '{func_name}': {e}"
    except Exception as e:  # noqa: BLE001 - reported back to the model
        return f"Error: Tool '{func_name}' failed: {e}"


def main():
    """Main agent loop."""
    args = parse_args()

    # Get API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        print("Create a .env file (see env.example) or export the key:")
        print("  export GEMINI_API_KEY='your-key-here'")
        sys.exit(1)

    if args.verbose:
        if len(api_key) > 8:
            print(f"✓ API Key loaded: {api_key[:4]}...{api_key[-4:]}")
        else:
            print(f"⚠️  Warning: API key seems too short ({len(api_key)} chars)")

    # Initialize Gemini client
    client = genai.Client(api_key=api_key)
    print("✓ Gemini client initialized\n")

    # Get user input
    user_prompt, is_recovery = get_user_input(args)

    # Initialize contents list with raw Content objects
    # This preserves thought_signature and other metadata
    contents: List[types.Content] = []

    # Add initial user message
    if is_recovery:
        initial_message = f"[RECOVERED CONTEXT]\n\n{user_prompt}\n\n[END RECOVERED CONTEXT]\n\nPlease continue the work from where we left off."
        print("🔄 Recovery mode: Continuing from previous context\n")
    else:
        initial_message = user_prompt
        print(f"\n📝 Task: {user_prompt}\n")

    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=initial_message)]
    ))

    # Get tool definitions and mapping
    tools = get_tool_definitions()
    tool_map = get_tool_map()

    # Get system prompt for config
    system_instruction = get_system_prompt()

    print("=" * 60)
    print("Starting Gemini Writing Agent")
    print("=" * 60)
    print(f"Model: {MODEL_NAME}")
    print(f"Max iterations: {MAX_ITERATIONS}")
    print(f"Context limit: {TOKEN_LIMIT:,} tokens")
    print(f"Auto-compression at: {COMPRESSION_THRESHOLD:,} tokens")
    print("=" * 60 + "\n")

    completed = False
    iteration = 0
    token_count = 0
    consecutive_errors = 0

    try:
        # Main agent loop
        for iteration in range(1, MAX_ITERATIONS + 1):
            print(f"\n{'─' * 60}")
            print(f"Iteration {iteration}/{MAX_ITERATIONS}")
            print(f"{'─' * 60}")

            # Token usage comes from the previous response - no extra API call.
            if token_count:
                print(f"📊 Current tokens: {token_count:,}/{TOKEN_LIMIT:,} "
                      f"({token_count/TOKEN_LIMIT*100:.1f}%)")

            contents, token_count = compress_if_needed(
                contents, system_instruction, client, token_count
            )

            # Auto-backup every N iterations
            if iteration % BACKUP_INTERVAL == 0:
                print(f"💾 Auto-backup (iteration {iteration})...")
                save_snapshot(contents, system_instruction, client, "Backup saved")

            # Configure generation with thinking enabled
            generate_config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                thinking_config=types.ThinkingConfig(
                    thinking_level="HIGH",
                ),
                tools=[tools],
                temperature=1.0,
            )

            # Call the model, retrying transient failures with backoff
            print("🤖 Calling Gemini model...\n")

            def on_retry(attempt: int, delay: float, error: BaseException) -> None:
                print(f"⚠️  API error ({type(error).__name__}: {error}). "
                      f"Retry {attempt}/{API_MAX_ATTEMPTS - 1} in {delay:.1f}s...")

            try:
                response = call_with_retry(
                    lambda: client.models.generate_content(
                        model=MODEL_NAME,
                        contents=contents,
                        config=generate_config,
                    ),
                    max_attempts=API_MAX_ATTEMPTS,
                    on_retry=on_retry,
                )
            except PermanentAPIError as e:
                print(f"\n✗ Unrecoverable API error: {e}")
                print("Check your API key and model name, then try again.")
                summary_file = save_snapshot(
                    contents, system_instruction, client, "Context saved"
                )
                print_recovery_hint(summary_file)
                sys.exit(1)
            except Exception as e:  # noqa: BLE001 - transient, already retried
                consecutive_errors += 1
                print(f"\n✗ Error during iteration {iteration}: {e}")
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"\n✗ {MAX_CONSECUTIVE_ERRORS} consecutive failures. Stopping.")
                    summary_file = save_snapshot(
                        contents, system_instruction, client, "Context saved"
                    )
                    print_recovery_hint(summary_file)
                    sys.exit(1)
                print(f"Continuing ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS} "
                      f"consecutive errors)...\n")
                continue

            consecutive_errors = 0

            # Track context size from the response itself
            usage = extract_usage(response)
            if usage["total"]:
                token_count = usage["total"]

            # Process the response
            thinking_text = ""
            content_text = ""
            function_calls_list = []

            # Get the model's response content (includes thought_signature)
            model_content = None
            if response.candidates and response.candidates[0].content:
                model_content = response.candidates[0].content

                # Process parts for display
                for part in model_content.parts or []:
                    # Handle thinking parts
                    if getattr(part, 'thought', None) and getattr(part, 'text', None):
                        thinking_text += part.text
                    # Handle function calls
                    elif getattr(part, 'function_call', None):
                        fc = part.function_call
                        function_calls_list.append({
                            "name": fc.name,
                            "args": dict(fc.args) if fc.args else {}
                        })
                    # Handle regular text
                    elif getattr(part, 'text', None):
                        content_text += part.text

            # Display thinking
            if thinking_text:
                print("=" * 60)
                print(f"🧠 Thinking (Iteration {iteration})")
                print("=" * 60)
                print(thinking_text)
                print("=" * 60 + "\n")

            # Display content
            if content_text:
                print("💬 Response:")
                print("-" * 60)
                print(content_text)
                print("-" * 60 + "\n")

            # CRITICAL: Append the FULL model response to contents
            # This preserves thought_signature for function calling
            if model_content:
                contents.append(model_content)

            # Check if the model called any functions
            if not function_calls_list:
                completed = True
                print("=" * 60)
                print("✅ TASK COMPLETED")
                print("=" * 60)
                print(f"Completed in {iteration} iteration(s)")
                print(f"Tokens used: {token_count:,}")
                print("=" * 60)
                break

            # Handle function calls
            print(f"\n🔧 Model decided to call {len(function_calls_list)} tool(s):")

            function_response_parts = []

            for fc in function_calls_list:
                func_name = fc["name"]
                tool_args = fc["args"]

                print(f"\n  → {func_name}")
                print(f"    Arguments: {json.dumps(tool_args, ensure_ascii=False, indent=6)}")

                result = execute_tool(
                    func_name, tool_args, tool_map, contents, system_instruction, client
                )

                # Print result (truncate if too long)
                if len(result) > 200:
                    print(f"    ✓ {result[:200]}...")
                else:
                    print(f"    ✓ {result}")

                function_response_parts.append(
                    types.Part.from_function_response(
                        name=func_name,
                        response={"result": result}
                    )
                )

            # Add all function responses as a single user turn
            contents.append(types.Content(
                role="user",
                parts=function_response_parts
            ))

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Saving context...")
        summary_file = save_snapshot(contents, system_instruction, client, "Context saved")
        print_recovery_hint(summary_file)
        sys.exit(0)

    # If we hit max iterations without finishing
    if not completed and iteration >= MAX_ITERATIONS:
        print("\n" + "=" * 60)
        print("⚠️  MAX ITERATIONS REACHED")
        print("=" * 60)
        print(f"\nReached maximum of {MAX_ITERATIONS} iterations.")
        print("Saving final context...")
        summary_file = save_snapshot(contents, system_instruction, client, "Context saved")
        print_recovery_hint(summary_file)


if __name__ == "__main__":
    main()
