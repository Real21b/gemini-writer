"""
WebSocket endpoint for real-time AI writing streaming.
"""

import asyncio
import json
import traceback
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import async_session
from backend.models import Project
from backend.services.writer_service import run_writer

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/write/{project_id}")
async def write_ws(websocket: WebSocket, project_id: str):
    """
    WebSocket endpoint that starts the AI writing agent for a project.

    The client connects, and the server streams events as JSON messages:
      - {"type": "status",      "data": {"message": "..."}}
      - {"type": "progress",    "data": {"iteration": N, ...}}
      - {"type": "thinking",    "data": {"text": "...", "iteration": N}}
      - {"type": "content",     "data": {"text": "...", "iteration": N}}
      - {"type": "tool_call",   "data": {"name": "...", "args": {...}}}
      - {"type": "tool_result", "data": {"name": "...", "result": "..."}}
      - {"type": "done",        "data": {"iteration": N, "message": "..."}}
      - {"type": "error",       "data": {"message": "..."}}
    """
    await websocket.accept()

    # Look up the project in the database
    async with async_session() as db:
        project = await db.get(Project, project_id)
        if not project:
            await websocket.send_json(
                {"type": "error", "data": {"message": "Project not found"}}
            )
            await websocket.close()
            return
        prompt = project.prompt
        # Mark project as running
        project.status = "running"
        await db.commit()

    # Event callback that pushes JSON through the WebSocket
    async def on_event(event_type: str, data: dict[str, Any]) -> None:
        try:
            await websocket.send_json({"type": event_type, "data": data})

            # Persist progress to DB periodically
            if event_type == "progress":
                async with async_session() as db:
                    proj = await db.get(Project, project_id)
                    if proj:
                        proj.current_iteration = data.get("iteration", 0)
                        proj.total_tokens = data.get("tokens", 0)
                        pct = int(
                            data.get("iteration", 0)
                            / max(data.get("max_iterations", 1), 1)
                            * 100
                        )
                        proj.progress = min(pct, 100)
                        await db.commit()

            elif event_type == "done":
                async with async_session() as db:
                    proj = await db.get(Project, project_id)
                    if proj:
                        proj.status = "completed"
                        proj.progress = 100
                        await db.commit()

            elif event_type == "error":
                async with async_session() as db:
                    proj = await db.get(Project, project_id)
                    if proj:
                        proj.status = "error"
                        proj.error_message = data.get("message", "Unknown error")
                        await db.commit()

        except WebSocketDisconnect:
            raise
        except Exception:
            pass  # Best-effort send

    try:
        await run_writer(
            prompt=prompt,
            project_id=project_id,
            on_event=on_event,
        )
    except WebSocketDisconnect:
        async with async_session() as db:
            proj = await db.get(Project, project_id)
            if proj and proj.status == "running":
                proj.status = "cancelled"
                await db.commit()
    except Exception as exc:
        try:
            await websocket.send_json(
                {"type": "error", "data": {"message": str(exc)}}
            )
        except Exception:
            pass
        async with async_session() as db:
            proj = await db.get(Project, project_id)
            if proj:
                proj.status = "error"
                proj.error_message = str(exc)
                await db.commit()
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
