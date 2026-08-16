"""
Configuration for the writing agent.

Two layers:

* ``Settings`` - process level, read from the environment (API key, output root)
* ``RunConfig`` - per run knobs (model, limits, budgets) that a CLI flag or, in
  phase 2, an HTTP request body can override.

Nothing in ``core`` reads ``os.environ`` outside of ``Settings.from_env``.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_MODEL = "gemini-3-flash-preview"


class ConfigError(RuntimeError):
    """Raised when the agent cannot be configured."""


@dataclass
class RunConfig:
    """Per-run settings."""

    model: str = DEFAULT_MODEL
    temperature: float = 1.0
    thinking_level: str = "HIGH"

    max_iterations: int = 300
    token_limit: int = 1_000_000

    # Compress well before the hard limit: a 900K token request is slow,
    # expensive, and the model's attention degrades long before that.
    compression_ratio: float = 0.65
    keep_recent_contents: int = 12

    backup_interval: int = 25
    stream: bool = True

    api_max_attempts: int = 5
    max_consecutive_errors: int = 5
    max_nudges: int = 2

    @property
    def compression_threshold(self) -> int:
        return int(self.token_limit * self.compression_ratio)


@dataclass
class Settings:
    """Process level settings."""

    api_key: str
    output_root: Path
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls, default_output_root: Optional[Path] = None) -> "Settings":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ConfigError(
                "GEMINI_API_KEY is not set. Create a .env file (see env.example) "
                "or export the key: export GEMINI_API_KEY='your-key-here'"
            )

        override = os.getenv("GEMINI_WRITER_OUTPUT_DIR", "").strip()
        if override:
            output_root = Path(override)
        elif default_output_root is not None:
            output_root = default_output_root
        else:
            output_root = Path(__file__).resolve().parent.parent / "output"

        return cls(
            api_key=api_key,
            output_root=output_root,
            model=os.getenv("GEMINI_WRITER_MODEL", "").strip() or DEFAULT_MODEL,
        )
