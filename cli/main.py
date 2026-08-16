"""
Command line interface.

A thin client over ``core``: parse arguments, build the run, render events.
No agent logic lives here.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from google import genai

from cli.renderer import ConsoleRenderer
from core.config import ConfigError, RunConfig, Settings
from core.events import EventType
from core.llm import GeminiLLM
from core.runner import AgentRunner
from core.workspace import Workspace

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NEEDS_INPUT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="writer.py",
        description="Gemini Writing Agent - create novels, books and short story collections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python writer.py "Create a collection of sci-fi short stories"
  python writer.py --recover output/my_project/.context_summary_20250107_143022.md
  python writer.py --model gemini-3-flash-preview --max-iterations 50 "Write a novella"
        """,
    )
    parser.add_argument("prompt", nargs="?", help='Your writing request, e.g. "Write a mystery novel"')
    parser.add_argument("--recover", metavar="PATH", help="Continue from a saved context summary")
    parser.add_argument("--model", help="Override the model for this run")
    parser.add_argument("--max-iterations", type=int, help="Maximum agent iterations")
    parser.add_argument("--temperature", type=float, help="Sampling temperature")
    parser.add_argument(
        "--thinking",
        choices=["LOW", "MEDIUM", "HIGH"],
        help="Thinking level (default HIGH)",
    )
    parser.add_argument("--output-dir", help="Where project folders are created")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    parser.add_argument("--verbose", action="store_true", help="Show token usage and raw events")
    return parser


def resolve_prompt(args: argparse.Namespace) -> Tuple[str, bool]:
    """Returns (prompt_or_context, is_recovery)."""
    if args.recover:
        path = Path(args.recover)
        if not path.exists():
            print(f"✗ Context summary not found: {path}")
            raise SystemExit(EXIT_FAILED)
        return path.read_text(encoding="utf-8"), True

    if args.prompt:
        return args.prompt, False

    print("=" * 60)
    print("Gemini Writing Agent")
    print("=" * 60)
    print("\nEnter your writing request (or 'quit' to exit):")
    print("Example: Create a collection of 15 sci-fi short stories\n")

    try:
        prompt = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye!")
        raise SystemExit(EXIT_OK) from None

    if prompt.lower() in ("quit", "exit", "q"):
        print("Goodbye!")
        raise SystemExit(EXIT_OK)
    if not prompt:
        print("Error: empty prompt. Please provide a writing request.")
        raise SystemExit(EXIT_FAILED)
    return prompt, False


def build_run_config(args: argparse.Namespace, settings: Settings) -> RunConfig:
    config = RunConfig(model=args.model or settings.model)
    if args.max_iterations:
        config.max_iterations = args.max_iterations
    if args.temperature is not None:
        config.temperature = args.temperature
    if args.thinking:
        config.thinking_level = args.thinking
    if args.no_stream:
        config.stream = False
    return config


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    try:
        settings = Settings.from_env(
            default_output_root=Path(args.output_dir) if args.output_dir else None
        )
    except ConfigError as exc:
        print(f"Error: {exc}")
        return EXIT_FAILED

    if args.output_dir:
        settings.output_root = Path(args.output_dir)

    prompt, is_recovery = resolve_prompt(args)
    config = build_run_config(args, settings)

    if args.verbose:
        key = settings.api_key
        preview = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "(too short)"
        print(f"✓ API key loaded: {preview}")
        print(f"✓ Output directory: {settings.output_root}")

    client = genai.Client(api_key=settings.api_key)
    workspace = Workspace(output_root=settings.output_root)
    runner = AgentRunner(llm=GeminiLLM(client, config), workspace=workspace, config=config)
    renderer = ConsoleRenderer(verbose=args.verbose)

    exit_code = EXIT_FAILED
    try:
        for event in runner.run(prompt, is_recovery=is_recovery):
            renderer.handle(event)
            if event.type is EventType.RUN_COMPLETED:
                exit_code = EXIT_OK
            elif event.type is EventType.RUN_NEEDS_INPUT:
                exit_code = EXIT_NEEDS_INPUT
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted. Saving context...")
        try:
            for event in runner.save_snapshot("interrupted"):
                renderer.handle(event)
        except Exception as exc:  # noqa: BLE001 - never mask the interrupt
            print(f"⚠️  Snapshot failed: {exc}")
        renderer.print_recovery_hint()
        return EXIT_OK

    return exit_code


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
