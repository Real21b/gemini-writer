"""File tools: write, read, list and patch."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.tools.base import ToolContext, ToolResult, tool

MAX_READ_CHARS = 60_000


class CreateProjectArgs(BaseModel):
    project_name: str = Field(
        description="Name for the project folder (sanitized for the filesystem)"
    )


@tool(
    name="create_project",
    description=(
        "Creates the project folder that all files are written into. Call this first, "
        "before writing anything. Calling it again with the same name reuses the folder."
    ),
    args_model=CreateProjectArgs,
)
def create_project(ctx: ToolContext, args: CreateProjectArgs) -> ToolResult:
    path, existed = ctx.workspace.create_project(args.project_name)
    verb = "Reusing existing" if existed else "Created"
    return ToolResult(
        f"{verb} project folder '{path.name}'. It is now the active project.",
        meta={"project_dir": str(path), "existed": existed},
    )


class WriteFileArgs(BaseModel):
    filename: str = Field(description="File name, e.g. 'chapter_01.md'")
    content: str = Field(description="The full content to write")
    mode: Literal["create", "append", "overwrite"] = Field(
        default="create",
        description=(
            "'create' for a new file (fails if it exists), 'append' to add to an existing "
            "file, 'overwrite' to replace it entirely"
        ),
    )


@tool(
    name="write_file",
    description=(
        "Writes a file in the project folder. Write complete, final prose - not outlines "
        "or placeholders. Prefer one 'create' call with the whole chapter over many appends."
    ),
    args_model=WriteFileArgs,
)
def write_file(ctx: ToolContext, args: WriteFileArgs) -> ToolResult:
    info = ctx.workspace.write(args.filename, args.content, args.mode)
    return ToolResult(
        f"Wrote '{info.path}' ({info.words:,} words, mode={args.mode}).",
        meta={"path": info.path, "bytes": info.bytes, "words": info.words, "mode": args.mode},
    )


class ReadFileArgs(BaseModel):
    filename: str = Field(description="File to read, e.g. 'chapter_02.md'")
    tail_chars: Optional[int] = Field(
        default=None,
        description=(
            "Read only the last N characters. Use this to check how the previous chapter "
            "ended before writing the next one."
        ),
    )


@tool(
    name="read_file",
    description=(
        "Reads a file you have already written. Use it to keep names, facts and timelines "
        "consistent, and to check how the previous chapter ended before continuing."
    ),
    args_model=ReadFileArgs,
)
def read_file(ctx: ToolContext, args: ReadFileArgs) -> ToolResult:
    if args.tail_chars:
        text = ctx.workspace.read_tail(args.filename, args.tail_chars)
    else:
        text = ctx.workspace.read(args.filename, max_chars=MAX_READ_CHARS)
    return ToolResult(text, meta={"path": args.filename, "chars": len(text)})


class ListFilesArgs(BaseModel):
    pass


@tool(
    name="list_files",
    description="Lists every file in the project with its word count. Use it to see what is done.",
    args_model=ListFilesArgs,
)
def list_files(ctx: ToolContext, args: ListFilesArgs) -> ToolResult:
    files = ctx.workspace.list_files()
    if not files:
        return ToolResult("The project is empty - no files written yet.", meta={"count": 0})

    listing = "\n".join(info.as_line() for info in files)
    total = sum(info.words for info in files)
    return ToolResult(
        f"{len(files)} file(s), {total:,} words total:\n{listing}",
        meta={"count": len(files), "total_words": total},
    )


class ApplyPatchArgs(BaseModel):
    filename: str = Field(description="File to edit")
    old_text: str = Field(
        description="Exact text to replace. Must appear exactly once - include surrounding context."
    )
    new_text: str = Field(description="Replacement text")


@tool(
    name="apply_patch",
    description=(
        "Replaces one exact passage in a file. Use this for targeted fixes (a name, a "
        "paragraph, a detail) instead of rewriting a whole chapter."
    ),
    args_model=ApplyPatchArgs,
)
def apply_patch(ctx: ToolContext, args: ApplyPatchArgs) -> ToolResult:
    info = ctx.workspace.apply_patch(args.filename, args.old_text, args.new_text)
    return ToolResult(
        f"Patched '{info.path}' ({info.words:,} words).",
        meta={"path": info.path, "bytes": info.bytes, "words": info.words, "mode": "patch"},
    )
