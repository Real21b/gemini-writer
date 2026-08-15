"""
Filesystem safety helpers.

Every path the agent proposes is resolved through this module so that a model
generated filename can never escape the active project folder.
"""

import os
from pathlib import Path
from typing import Iterable


# Extensions the agent is allowed to write. Anything else is rejected.
ALLOWED_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})

# Guard rails against pathological filenames.
MAX_FILENAME_LENGTH = 200
MAX_PATH_DEPTH = 5
MAX_FILE_BYTES = 5_000_000


class UnsafePathError(ValueError):
    """Raised when a proposed filename is rejected."""


def _validate_parts(parts: Iterable[str]) -> None:
    for part in parts:
        if part in ("..", "."):
            raise UnsafePathError("Path traversal is not allowed in filenames.")
        if part.startswith("."):
            raise UnsafePathError("Hidden files and folders are not allowed.")
        if part.strip() != part or not part.strip():
            raise UnsafePathError("Path segments cannot be empty or padded with spaces.")


def resolve_in_project(project_folder: str, filename: str) -> Path:
    """
    Resolve a model supplied filename inside the project folder.

    Relative sub-directories are allowed (e.g. "chapters/ch_01.md"); anything
    that resolves outside the project folder is rejected.

    Args:
        project_folder: The active project folder
        filename: The filename proposed by the agent

    Returns:
        The absolute path to write to

    Raises:
        UnsafePathError: If the filename is rejected
    """
    if not isinstance(filename, str) or not filename.strip():
        raise UnsafePathError("Filename must be a non-empty string.")

    filename = filename.strip().replace("\\", "/")

    if "\x00" in filename or any(ord(ch) < 32 for ch in filename):
        raise UnsafePathError("Filename contains control characters.")

    if len(filename) > MAX_FILENAME_LENGTH:
        raise UnsafePathError(
            f"Filename is too long ({len(filename)} > {MAX_FILENAME_LENGTH} characters)."
        )

    if filename.startswith("/") or os.path.isabs(filename) or ":" in filename:
        raise UnsafePathError("Absolute paths are not allowed.")

    parts = [part for part in filename.split("/") if part != ""]
    if not parts:
        raise UnsafePathError("Filename must contain a file name.")
    if len(parts) > MAX_PATH_DEPTH:
        raise UnsafePathError(f"Path is nested too deeply (max {MAX_PATH_DEPTH} levels).")

    _validate_parts(parts)

    root = Path(project_folder).resolve()
    candidate = (root / "/".join(parts)).resolve()

    if candidate != root and root not in candidate.parents:
        raise UnsafePathError("Writing outside of the project folder is not allowed.")

    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise UnsafePathError(
            f"Extension '{candidate.suffix or '(none)'}' is not allowed. Allowed: {allowed}"
        )

    return candidate


def normalize_filename(filename: str) -> str:
    """Append the default markdown extension when no allowed extension is given."""
    if not isinstance(filename, str):
        return filename
    stripped = filename.strip()
    suffix = Path(stripped.replace("\\", "/")).suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return stripped
    return stripped + ".md"
