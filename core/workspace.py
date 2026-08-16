"""
The workspace: the only place in the agent that touches the filesystem.

This replaces the module level ``_active_project_folder`` global. Every run owns
one ``Workspace`` instance, so two runs in the same process (a web server, a
test suite) can never write into each other's project.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Extensions the agent is allowed to write. Anything else is rejected.
ALLOWED_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})

MAX_FILENAME_LENGTH = 200
MAX_PATH_DEPTH = 5
MAX_FILE_BYTES = 5_000_000


class WorkspaceError(RuntimeError):
    """Base class for workspace failures reported back to the model."""


class UnsafePathError(WorkspaceError, ValueError):
    """Raised when a proposed filename is rejected."""


class NoProjectError(WorkspaceError):
    """Raised when a file operation happens before a project exists."""


@dataclass(frozen=True)
class FileInfo:
    path: str
    bytes: int
    words: int

    def as_line(self) -> str:
        return f"{self.path} ({self.words:,} words, {self.bytes:,} bytes)"


def sanitize_folder_name(name: str) -> str:
    """Sanitizes a folder name for filesystem compatibility."""
    name = (name or "").strip().replace(" ", "_")
    name = re.sub(r"[^\w\-]", "", name)
    name = name.strip("-_")
    return name or "untitled_project"


def normalize_filename(filename: str) -> str:
    """Append the default markdown extension when no allowed extension is given."""
    if not isinstance(filename, str):
        return filename
    stripped = filename.strip()
    suffix = Path(stripped.replace("\\", "/")).suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return stripped
    return stripped + ".md"


def _validate_segments(parts: List[str]) -> None:
    for part in parts:
        if part in ("..", "."):
            raise UnsafePathError("Path traversal is not allowed in filenames.")
        if part.startswith("."):
            raise UnsafePathError("Hidden files and folders are not allowed.")
        if part.strip() != part or not part.strip():
            raise UnsafePathError("Path segments cannot be empty or padded with spaces.")


class Workspace:
    """A project folder plus the safe file operations allowed inside it."""

    def __init__(self, output_root: Path, project_dir: Optional[Path] = None) -> None:
        self.output_root = Path(output_root)
        self._project_dir = Path(project_dir) if project_dir else None

    # --- project lifecycle ---------------------------------------------------

    @property
    def project_dir(self) -> Optional[Path]:
        return self._project_dir

    @property
    def is_ready(self) -> bool:
        return self._project_dir is not None

    def create_project(self, project_name: str) -> tuple[Path, bool]:
        """
        Create (or adopt) a project folder and make it active.

        Returns:
            (path, existed_before)
        """
        project_path = self.output_root / sanitize_folder_name(project_name)
        existed = project_path.exists()
        project_path.mkdir(parents=True, exist_ok=True)
        self._project_dir = project_path
        return project_path, existed

    def require_project(self) -> Path:
        if self._project_dir is None:
            raise NoProjectError(
                "No active project folder. Call create_project first."
            )
        return self._project_dir

    # --- path safety ---------------------------------------------------------

    def resolve(self, filename: str) -> Path:
        """
        Resolve a model supplied filename inside the project folder.

        Relative sub-directories are allowed ("chapters/ch_01.md"); anything
        resolving outside the project folder is rejected.
        """
        root = self.require_project().resolve()

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

        parts = [part for part in filename.split("/") if part]
        if not parts:
            raise UnsafePathError("Filename must contain a file name.")
        if len(parts) > MAX_PATH_DEPTH:
            raise UnsafePathError(f"Path is nested too deeply (max {MAX_PATH_DEPTH} levels).")

        _validate_segments(parts)

        candidate = (root / "/".join(parts)).resolve()
        if candidate != root and root not in candidate.parents:
            raise UnsafePathError("Writing outside of the project folder is not allowed.")

        if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
            raise UnsafePathError(
                f"Extension '{candidate.suffix or '(none)'}' is not allowed. Allowed: {allowed}"
            )

        return candidate

    def relative(self, path: Path) -> str:
        root = self.require_project().resolve()
        return str(Path(path).resolve().relative_to(root))

    # --- file operations -----------------------------------------------------

    def write(self, filename: str, content: str, mode: str = "create") -> FileInfo:
        if mode not in ("create", "append", "overwrite"):
            raise WorkspaceError(
                f"Invalid mode '{mode}'. Use 'create', 'append', or 'overwrite'."
            )
        if content is None:
            raise WorkspaceError("No content provided.")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceError(
                f"Content is too large ({len(content):,} characters). "
                f"Split it across multiple files (limit: {MAX_FILE_BYTES:,} bytes)."
            )

        path = self.resolve(normalize_filename(filename))

        if mode == "create" and path.exists():
            raise WorkspaceError(
                f"File '{filename}' already exists. Use 'append' or 'overwrite' to modify it."
            )
        if mode == "append" and not path.exists():
            # Silently creating a file here hides the model's typo (B-13).
            raise WorkspaceError(
                f"File '{filename}' does not exist. Use 'create' mode to start it."
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding="utf-8")

        return self.info(path)

    def read(self, filename: str, max_chars: Optional[int] = None) -> str:
        path = self.resolve(normalize_filename(filename))
        if not path.exists():
            raise WorkspaceError(f"File '{filename}' does not exist.")
        text = path.read_text(encoding="utf-8")
        if max_chars is not None and len(text) > max_chars:
            return text[:max_chars] + f"\n\n[... truncated, {len(text) - max_chars:,} more characters]"
        return text

    def read_tail(self, filename: str, chars: int) -> str:
        """Read the last ``chars`` characters - used for chapter-to-chapter continuity."""
        path = self.resolve(normalize_filename(filename))
        if not path.exists():
            raise WorkspaceError(f"File '{filename}' does not exist.")
        text = path.read_text(encoding="utf-8")
        return text[-chars:] if len(text) > chars else text

    def apply_patch(self, filename: str, old_text: str, new_text: str) -> FileInfo:
        """Replace one unique occurrence of ``old_text`` - cheaper than rewriting a chapter."""
        path = self.resolve(normalize_filename(filename))
        if not path.exists():
            raise WorkspaceError(f"File '{filename}' does not exist.")
        if not old_text:
            raise WorkspaceError("old_text must not be empty.")

        text = path.read_text(encoding="utf-8")
        occurrences = text.count(old_text)
        if occurrences == 0:
            raise WorkspaceError(
                f"old_text was not found in '{filename}'. Read the file first and copy the exact text."
            )
        if occurrences > 1:
            raise WorkspaceError(
                f"old_text appears {occurrences} times in '{filename}'. Include more surrounding "
                "text so it matches exactly once."
            )

        path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return self.info(path)

    def exists(self, filename: str) -> bool:
        try:
            return self.resolve(normalize_filename(filename)).exists()
        except WorkspaceError:
            return False

    def list_files(self) -> List[FileInfo]:
        root = self.require_project()
        files = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            files.append(self.info(path))
        return files

    def info(self, path: Path) -> FileInfo:
        text = ""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
        return FileInfo(
            path=self.relative(path),
            bytes=path.stat().st_size,
            words=len(text.split()),
        )

    def total_words(self) -> int:
        return sum(info.words for info in self.list_files())

    # --- snapshots -----------------------------------------------------------

    def snapshot_path(self, timestamp: str) -> Path:
        """Recovery snapshots are hidden files, so they never show up in list_files."""
        root = self._project_dir or self.output_root
        root.mkdir(parents=True, exist_ok=True)
        return root / f".context_summary_{timestamp}.md"
