"""
Agent tools.

Importing this package registers every tool in the shared REGISTRY.
"""

from core.tools import bible, control, files  # noqa: F401 - imported for registration
from core.tools.base import (
    REGISTRY,
    ToolContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    pydantic_to_genai_schema,
    tool,
)

__all__ = [
    "REGISTRY",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "pydantic_to_genai_schema",
    "tool",
]
