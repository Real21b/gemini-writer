"""
REST API routes for project management.
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.models import Project, ProjectStatus
from backend.schemas import (
    ProjectCreate,
    ProjectResponse,
    ProjectListResponse,
    FileInfo,
    FileContent,
    ProjectFiles,
)
from tools.project import sanitize_folder_name

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    skip: int = 0,
    limit: int = 20,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all projects with optional status filter."""
    query = select(Project).order_by(Project.created_at.desc())
    if status:
        query = query.where(Project.status == status)
    total_q = select(func.count(Project.id))
    if status:
        total_q = total_q.where(Project.status == status)
    total = (await db.execute(total_q)).scalar() or 0
    results = (await db.execute(query.offset(skip).limit(limit))).scalars().all()
    return ProjectListResponse(
        projects=[ProjectResponse.model_validate(p) for p in results],
        total=total,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new writing project (does not start generation)."""
    folder_name = sanitize_folder_name(body.name)
    project = Project(
        name=body.name,
        folder_name=folder_name,
        prompt=body.prompt,
        status=ProjectStatus.PENDING,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Get a project by ID."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a project."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
    await db.commit()


@router.get("/{project_id}/files", response_model=ProjectFiles)
async def list_project_files(project_id: str, db: AsyncSession = Depends(get_db)):
    """List all files in a project's output folder."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    output_dir = os.path.join(settings.output_dir, project.folder_name)
    files: list[FileInfo] = []
    if os.path.isdir(output_dir):
        for fname in sorted(os.listdir(output_dir)):
            fpath = os.path.join(output_dir, fname)
            if os.path.isfile(fpath) and not fname.startswith("."):
                stat = os.stat(fpath)
                files.append(
                    FileInfo(
                        name=fname,
                        size=stat.st_size,
                        modified_at=datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ),
                    )
                )
    return ProjectFiles(project_id=project_id, files=files)


@router.get("/{project_id}/files/{filename}", response_model=FileContent)
async def get_project_file(
    project_id: str, filename: str, db: AsyncSession = Depends(get_db)
):
    """Read a specific file from a project."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    safe_filename = os.path.basename(filename)
    project_dir = os.path.realpath(
        os.path.join(settings.output_dir, project.folder_name)
    )
    file_path = os.path.realpath(os.path.join(project_dir, safe_filename))

    # Ensure the resolved path stays inside the project directory
    if not file_path.startswith(project_dir + os.sep):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    with open(file_path, "r", encoding="utf-8") as f:  # noqa: S603
        content = f.read()

    return FileContent(name=safe_filename, content=content, size=len(content))
