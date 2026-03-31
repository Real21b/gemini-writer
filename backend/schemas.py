"""
Pydantic schemas for API request/response models.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Project Schemas ──────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    """Schema for creating a new project."""

    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    prompt: str = Field(
        ..., min_length=1, max_length=10000, description="Writing prompt"
    )


class ProjectResponse(BaseModel):
    """Schema for project response."""

    id: str
    name: str
    folder_name: str
    prompt: str
    status: str
    progress: int
    current_iteration: int
    total_tokens: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """Schema for listing projects."""

    projects: list[ProjectResponse]
    total: int


# ── File Schemas ─────────────────────────────────────────────────────────


class FileInfo(BaseModel):
    """Schema for file information."""

    name: str
    size: int
    modified_at: datetime


class FileContent(BaseModel):
    """Schema for file content."""

    name: str
    content: str
    size: int


class ProjectFiles(BaseModel):
    """Schema for listing project files."""

    project_id: str
    files: list[FileInfo]


# ── WebSocket Message Schemas ────────────────────────────────────────────


class WSMessage(BaseModel):
    """Base WebSocket message schema."""

    type: str
    data: dict = Field(default_factory=dict)
