"""
Story bible tools.

The agent's long-term memory. Context gets compressed and chapters scroll out of
the window; the story bible is the one file that survives and is re-read before
every chapter, which is what keeps names, places and timelines consistent across
a 100,000 word manuscript.
"""

from typing import Dict, List, Literal, Tuple

from pydantic import BaseModel, Field

from core.tools.base import ToolContext, ToolResult, tool

BIBLE_FILENAME = "story_bible.md"

BIBLE_TEMPLATE = """# Story Bible

Living reference for this project. Update it whenever a fact is established.

## Premise

## Characters

## Places

## Timeline

## Continuity Notes
"""


def parse_sections(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Split a markdown document into (preamble, [(heading, body), ...]) on '## ' headings."""
    lines = text.splitlines()
    preamble: List[str] = []
    sections: List[Tuple[str, List[str]]] = []

    for line in lines:
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)

    return (
        "\n".join(preamble).strip(),
        [(heading, "\n".join(body).strip()) for heading, body in sections],
    )


def render_sections(preamble: str, sections: List[Tuple[str, str]]) -> str:
    parts = [preamble.strip()] if preamble.strip() else []
    for heading, body in sections:
        parts.append(f"## {heading}\n\n{body.strip()}" if body.strip() else f"## {heading}")
    return "\n\n".join(parts).strip() + "\n"


def merge_section(text: str, section: str, content: str, mode: str) -> str:
    """Replace or extend one '## section' of the bible, preserving the rest."""
    preamble, sections = parse_sections(text)
    lowered = section.strip().lower()

    for index, (heading, body) in enumerate(sections):
        if heading.lower() == lowered:
            new_body = content.strip() if mode == "replace" else f"{body}\n\n{content.strip()}"
            sections[index] = (heading, new_body.strip())
            break
    else:
        sections.append((section.strip(), content.strip()))

    return render_sections(preamble, sections)


class ReadStoryBibleArgs(BaseModel):
    pass


@tool(
    name="read_story_bible",
    description=(
        "Reads the story bible: premise, characters, places, timeline and continuity notes. "
        "Read it before writing each chapter so the details stay consistent."
    ),
    args_model=ReadStoryBibleArgs,
)
def read_story_bible(ctx: ToolContext, args: ReadStoryBibleArgs) -> ToolResult:
    if not ctx.workspace.exists(BIBLE_FILENAME):
        return ToolResult(
            "No story bible yet. Create one with update_story_bible before writing chapters.",
            meta={"exists": False},
        )
    text = ctx.workspace.read(BIBLE_FILENAME)
    return ToolResult(text, meta={"exists": True, "chars": len(text)})


class UpdateStoryBibleArgs(BaseModel):
    section: str = Field(
        description="Section to update, e.g. 'Characters', 'Places', 'Timeline', 'Continuity Notes'"
    )
    content: str = Field(description="The facts to record, as markdown")
    mode: Literal["append", "replace"] = Field(
        default="append",
        description="'append' adds to the section, 'replace' rewrites it",
    )


@tool(
    name="update_story_bible",
    description=(
        "Records established facts in the story bible. Call it after each chapter with any "
        "new character, place, date or detail that later chapters must respect."
    ),
    args_model=UpdateStoryBibleArgs,
)
def update_story_bible(ctx: ToolContext, args: UpdateStoryBibleArgs) -> ToolResult:
    workspace = ctx.workspace
    exists = workspace.exists(BIBLE_FILENAME)
    current = workspace.read(BIBLE_FILENAME) if exists else BIBLE_TEMPLATE

    merged = merge_section(current, args.section, args.content, args.mode)
    info = workspace.write(BIBLE_FILENAME, merged, "overwrite" if exists else "create")

    return ToolResult(
        f"Story bible updated ('{args.section}', {info.words:,} words total).",
        meta={"path": info.path, "bytes": info.bytes, "words": info.words, "section": args.section},
    )


def bible_digest(workspace, max_chars: int = 4000) -> str:
    """A compact view of the bible, injected into the context after compression."""
    if not workspace.is_ready or not workspace.exists(BIBLE_FILENAME):
        return ""
    text = workspace.read(BIBLE_FILENAME)
    return text if len(text) <= max_chars else text[:max_chars] + "\n[... bible truncated]"


def section_index(text: str) -> Dict[str, str]:
    """Convenience accessor used by tests."""
    return {heading: body for heading, body in parse_sections(text)[1]}
