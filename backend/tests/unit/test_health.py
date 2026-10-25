from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.health import get_checks
from app.main import create_app


async def _ok() -> None:
    return None


async def _down() -> None:
    raise ConnectionError("unreachable")


@pytest.fixture
def app():
    return create_app()


async def _get(app, checks):
    app.dependency_overrides[get_checks] = lambda: checks
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/api/health")


async def test_health_ok_when_all_dependencies_reachable(app):
    resp = await _get(app, {"database": _ok, "redis": _ok})
    assert resp.status_code == 200
    assert resp.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_health_503_names_failing_dependency(app):
    resp = await _get(app, {"database": _ok, "redis": _down})
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == "error: ConnectionError"


async def test_unknown_route_returns_problem_json(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "HTTP_404"
