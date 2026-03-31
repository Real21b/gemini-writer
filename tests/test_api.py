"""
Tests for the FastAPI backend API endpoints.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.core.database import init_db, engine, Base


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test and drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Health ────────────────────────────────────────────────────────────


class TestHealth:
    async def test_health_endpoint(self, client: AsyncClient):
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "version" in data


# ── Projects CRUD ─────────────────────────────────────────────────────


class TestProjects:
    async def test_list_projects_empty(self, client: AsyncClient):
        res = await client.get("/api/projects")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 0
        assert data["projects"] == []

    async def test_create_project(self, client: AsyncClient):
        res = await client.post(
            "/api/projects",
            json={"name": "Test Novel", "prompt": "Write a novel about space."},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "Test Novel"
        assert data["status"] == "pending"
        assert data["folder_name"] == "Test_Novel"

    async def test_get_project(self, client: AsyncClient):
        create_res = await client.post(
            "/api/projects",
            json={"name": "Project X", "prompt": "A prompt."},
        )
        pid = create_res.json()["id"]
        res = await client.get(f"/api/projects/{pid}")
        assert res.status_code == 200
        assert res.json()["name"] == "Project X"

    async def test_get_project_not_found(self, client: AsyncClient):
        res = await client.get("/api/projects/nonexistent")
        assert res.status_code == 404

    async def test_delete_project(self, client: AsyncClient):
        create_res = await client.post(
            "/api/projects",
            json={"name": "Delete Me", "prompt": "Something."},
        )
        pid = create_res.json()["id"]
        del_res = await client.delete(f"/api/projects/{pid}")
        assert del_res.status_code == 204
        get_res = await client.get(f"/api/projects/{pid}")
        assert get_res.status_code == 404

    async def test_list_projects_with_data(self, client: AsyncClient):
        await client.post(
            "/api/projects",
            json={"name": "A", "prompt": "prompt A"},
        )
        await client.post(
            "/api/projects",
            json={"name": "B", "prompt": "prompt B"},
        )
        res = await client.get("/api/projects")
        data = res.json()
        assert data["total"] == 2
        assert len(data["projects"]) == 2
