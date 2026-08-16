"""
Control tools: how a run ends.

Without an explicit ``finish_task`` the loop had to guess: any turn without a
tool call was treated as "done", so a model that paused to ask a question or
wrote a short status note ended the run with half a novel on disk (B-08).
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from core.tools.base import ToolContext, ToolResult, tool


class FinishTaskArgs(BaseModel):
    summary: str = Field(description="What was written, in two or three sentences")
    files_written: Optional[List[str]] = Field(
        default=None, description="The files that make up the finished work"
    )


@tool(
    name="finish_task",
    description=(
        "Call this once the whole task is complete and every file is written. This is the "
        "only way to end the run - never stop by simply replying with text."
    ),
    args_model=FinishTaskArgs,
)
def finish_task(ctx: ToolContext, args: FinishTaskArgs) -> ToolResult:
    files = args.files_written or [info.path for info in ctx.workspace.list_files()]
    total_words = ctx.workspace.total_words() if ctx.workspace.is_ready else 0

    ctx.finished = {
        "summary": args.summary,
        "files": files,
        "total_words": total_words,
    }
    return ToolResult(
        f"Task marked complete: {len(files)} file(s), {total_words:,} words.",
        meta={"files": files, "total_words": total_words},
    )


class AskUserArgs(BaseModel):
    question: str = Field(description="The single question that is blocking progress")


@tool(
    name="ask_user",
    description=(
        "Asks the user a question when a decision genuinely cannot be made without them. "
        "Use it sparingly: prefer making a sensible choice and noting it in the story bible."
    ),
    args_model=AskUserArgs,
)
def ask_user(ctx: ToolContext, args: AskUserArgs) -> ToolResult:
    ctx.question = args.question
    return ToolResult(f"Question sent to the user: {args.question}", meta={"question": args.question})
