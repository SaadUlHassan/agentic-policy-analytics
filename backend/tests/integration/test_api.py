"""REST + WebSocket API against real Postgres and Redis."""

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect

from app.db.session import get_sessionmaker
from app.jobs.lifecycle import claim, create_analysis
from app.jobs.writer import FencedWriter
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(sessions, database_url):
    # NullPool: TestClient runs the app on its own event loop, and pooled asyncpg connections are loop-bound.
    engine = create_async_engine(database_url, poolclass=NullPool)
    app = create_app()
    app.dependency_overrides[get_sessionmaker] = lambda: async_sessionmaker(engine, expire_on_commit=False)
    with TestClient(app) as c:
        yield c


async def _running_analysis(sessions, events: list[tuple[str, str]]) -> tuple[str, FencedWriter]:
    async with sessions() as session:
        analysis = await create_analysis(session, "ICT employment")
    async with sessions() as session:
        from sqlalchemy import select

        from app.db.models import OutboxIntent

        intent = await session.scalar(select(OutboxIntent.id).where(OutboxIntent.analysis_id == analysis.id))
    claimed = await claim(sessions, analysis.id, intent, "test")
    writer = FencedWriter(sessions, None, analysis.id, claimed.epoch)
    for agent, title in events:
        await writer.emit(agent, "rationale", title)
    return analysis.id, writer


def test_create_validates_and_queues(client):
    bad = client.post("/api/analyses", json={"query": "hi"})
    assert bad.status_code == 422 and bad.headers["content-type"].startswith("application/problem+json")
    resp = client.post("/api/analyses", json={"query": "  Analyse ICT employment 2020-2024  "})
    assert resp.status_code == 202 and resp.json()["status"] == "queued"
    detail = client.get(f"/api/analyses/{resp.json()['id']}").json()
    assert detail["query"] == "Analyse ICT employment 2020-2024" and detail["report"] is None


def test_unknown_analysis_is_404_problem(client):
    resp = client.get("/api/analyses/does-not-exist")
    assert resp.status_code == 404 and resp.json()["code"] == "ANALYSIS_NOT_FOUND"


def test_history_pages_newest_first_with_a_cursor(client):
    ids = [client.post("/api/analyses", json={"query": f"question {i}"}).json()["id"] for i in range(3)]
    first = client.get("/api/analyses", params={"limit": 2}).json()
    second = client.get("/api/analyses", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    seen = [a["id"] for a in first["items"] + second["items"]]
    assert seen == list(reversed(ids)) and second["next_cursor"] is None
    assert client.get("/api/analyses", params={"cursor": "%%%"}).status_code == 400


async def test_websocket_replays_then_closes_after_terminal_status(client, sessions):
    analysis_id, writer = await _running_analysis(
        sessions, [("coordinator", "plan"), ("extraction", "fetch")]
    )
    from app.db.models import AnalysisStatus

    await writer.finish(AnalysisStatus.COMPLETED, report={"findings": []})
    with client.websocket_connect(f"/ws/analyses/{analysis_id}") as ws:
        received = [ws.receive_json() for _ in range(3)]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert [e["seq"] for e in received] == [1, 2, 3] and received[-1]["detail"] == {"status": "completed"}


async def test_websocket_resumes_from_cursor(client, sessions):
    analysis_id, writer = await _running_analysis(sessions, [("a", "1"), ("a", "2"), ("a", "3")])
    from app.db.models import AnalysisStatus

    await writer.finish(AnalysisStatus.COMPLETED)
    with client.websocket_connect(f"/ws/analyses/{analysis_id}?after_seq=2") as ws:
        assert [ws.receive_json()["seq"] for _ in range(2)] == [3, 4]


async def test_event_committed_without_a_hint_still_arrives(client, sessions, database_url):
    analysis_id, _ = await _running_analysis(sessions, [("coordinator", "plan")])
    with client.websocket_connect(f"/ws/analyses/{analysis_id}") as ws:
        assert ws.receive_json()["seq"] == 1
        # Commit a terminal event directly, with no Redis publish: the reader's timer must find it.
        with psycopg.connect(database_url.replace("+asyncpg", "")) as conn:
            conn.execute("UPDATE analyses SET last_event_seq = 2 WHERE id = %s", (analysis_id,))
            conn.execute(
                "INSERT INTO analysis_events (analysis_id, seq, agent, type, title, detail) "
                "VALUES (%s, 2, 'system', 'status', 'done', '{\"status\": \"completed\"}')",
                (analysis_id,),
            )
        assert ws.receive_json()["detail"] == {"status": "completed"}


def test_websocket_for_unknown_analysis_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/ws/analyses/nope") as ws:
        ws.receive_json()
    assert exc.value.code == 4404


async def test_client_resuming_after_the_terminal_event_is_closed_not_left_waiting(client, sessions):
    analysis_id, writer = await _running_analysis(sessions, [("a", "1")])
    from app.db.models import AnalysisStatus

    await writer.finish(AnalysisStatus.COMPLETED)
    with (
        client.websocket_connect(f"/ws/analyses/{analysis_id}?after_seq=2") as ws,
        pytest.raises(WebSocketDisconnect),
    ):
        ws.receive_json()


async def test_clarify_answers_once_then_409s_and_get_shows_the_question(client, sessions):
    analysis_id, writer = await _running_analysis(sessions, [])
    version = await writer.pause(
        "i-1", {"question": "Which sector?", "options": ["ICT", "Finance"]}, active_ms=5
    )
    detail = client.get(f"/api/analyses/{analysis_id}").json()
    assert detail["status"] == "awaiting_input"
    assert (
        detail["clarification"]["question"] == "Which sector?"
        and detail["clarification"]["version"] == version
    )

    both = client.post(
        f"/api/analyses/{analysis_id}/clarify",
        json={"clarification_version": version, "answer": "ICT", "proceed_with_assumptions": True},
    )
    assert both.status_code == 422
    ok = client.post(
        f"/api/analyses/{analysis_id}/clarify", json={"clarification_version": version, "answer": "ICT"}
    )
    assert ok.status_code == 202 and ok.json()["status"] == "queued"
    again = client.post(
        f"/api/analyses/{analysis_id}/clarify", json={"clarification_version": version, "answer": "ICT"}
    )
    assert again.status_code == 409 and again.json()["code"] == "CLARIFICATION_STALE"
    assert client.get(f"/api/analyses/{analysis_id}").json()["clarification"] is None


def test_clarify_and_cancel_unknown_analysis_are_404(client):
    for path, body in (
        ("clarify", {"clarification_version": 1, "proceed_with_assumptions": True}),
        ("cancel", None),
    ):
        resp = client.post(f"/api/analyses/missing/{path}", json=body)
        assert resp.status_code == 404 and resp.json()["code"] == "ANALYSIS_NOT_FOUND"


def test_cancel_queued_then_already_terminal(client):
    analysis_id = client.post("/api/analyses", json={"query": "Analyse ICT employment"}).json()["id"]
    first = client.post(f"/api/analyses/{analysis_id}/cancel")
    assert first.status_code == 202 and first.json()["status"] == "cancelled"
    second = client.post(f"/api/analyses/{analysis_id}/cancel")
    assert second.status_code == 409 and second.json()["code"] == "ALREADY_TERMINAL"
    assert client.get(f"/api/analyses/{analysis_id}").json()["status"] == "cancelled"


async def test_cancel_running_is_a_request(client, sessions):
    analysis_id, _ = await _running_analysis(sessions, [])
    resp = client.post(f"/api/analyses/{analysis_id}/cancel")
    assert resp.status_code == 202 and resp.json() == {
        "id": analysis_id,
        "status": "running",
        "cancel_requested": True,
    }
    assert client.get(f"/api/analyses/{analysis_id}").json()["cancel_requested"] is True
