"""
File writing tool for creating and managing markdown files.
"""

from typing import Literal

from .paths import MAX_FILE_BYTES, UnsafePathError, normalize_filename, resolve_in_project
from .project import get_active_project_folder


def write_file_impl(filename: str, content: str, mode: Literal["create", "append", "overwrite"]) -> str:
    """
    Writes content to a markdown file in the active project folder.

    Args:
        filename: The name of the file to write
        content: The content to write
        mode: The write mode - 'create', 'append', or 'overwrite'

    Returns:
        Success message or error message
    """
    # Check if project folder is initialized
    project_folder = get_active_project_folder()
    if not project_folder:
        return "Error: No active project folder. Please create a project first using create_project."

    if mode not in ("create", "append", "overwrite"):
        return f"Error: Invalid mode '{mode}'. Use 'create', 'append', or 'overwrite'."

    if content is None:
        return "Error: No content provided."

    # Resolve the path safely - this rejects traversal, absolute paths and
    # disallowed extensions before anything touches the filesystem.
    filename = normalize_filename(filename)
    try:
        file_path = resolve_in_project(project_folder, filename)
    except UnsafePathError as e:
        return f"Error: {e}"

    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        return (
            f"Error: Content is too large ({len(content):,} characters). "
            f"Split it across multiple files (limit: {MAX_FILE_BYTES:,} bytes)."
        )

    try:
        if mode == "create":
            # Create mode: fail if file exists
            if file_path.exists():
                return f"Error: File '{filename}' already exists. Use 'append' or 'overwrite' mode to modify it."

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully created file '{filename}' with {len(content)} characters."

        elif mode == "append":
            # Append mode: add to end of file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("a", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully appended {len(content)} characters to '{filename}'."

        else:
            # Overwrite mode: replace entire file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully overwrote '{filename}' with {len(content)} characters."

    except OSError as e:
        return f"Error writing file '{filename}': {str(e)}"
