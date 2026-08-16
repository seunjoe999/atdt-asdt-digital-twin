"""Exercises the full ASDT lifecycle (sync -> gap detection -> negotiate with
ATDT's Tutoring Channel -> report -> resync -> gap resolution) with ATDT
itself replaced by a monkeypatched fake, so this suite runs without a live
ATDT server. The live-integration check (against the real ATDT service) is
done separately, by hand, as documented in the top-level README.
"""

from __future__ import annotations

import app.atdt_client as atdt_client

FAKE_WHOAMI = {"id": 1, "email": "student@example.com", "full_name": "A. Student", "role": "student"}


def _auth_header():
    return {"Authorization": "Bearer fake-atdt-token"}


async def _fake_whoami(token):
    return FAKE_WHOAMI


def test_gap_detection_negotiation_and_resolution(client, monkeypatch):
    monkeypatch.setattr(atdt_client, "whoami", _fake_whoami)

    async def low_score_attempts(token, course_id):
        return [
            {
                "id": 1,
                "assessment_id": 1,
                "assessment_title": "Quiz 1",
                "topic": "Graph Traversal",
                "total_score": 30.0,
                "submitted_at": "2026-08-16T00:00:00Z",
            }
        ]

    monkeypatch.setattr(atdt_client, "get_my_attempts", low_score_attempts)

    r = client.post("/asdt/sync", json={"course_id": 1}, headers=_auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["new_gaps"]) == 1
    assert body["new_gaps"][0]["topic"] == "Graph Traversal"
    assert body["knowledge_states"][0]["mastery"] == 0.3
    gap_id = body["new_gaps"][0]["id"]

    r = client.get("/asdt/gaps", params={"course_id": 1}, headers=_auth_header())
    assert r.status_code == 200
    gaps = r.json()
    assert len(gaps) == 1
    assert gaps[0]["status"] == "open"

    async def fake_ask_tutor(token, course_id, question):
        assert "Graph Traversal" in question
        return {
            "conversation_id": 1,
            "answer": "A graph traversal visits every node reachable from a start node...",
            "citations": [{"source_document": "notes.pdf", "page_number": 3, "excerpt": "..."}],
        }

    monkeypatch.setattr(atdt_client, "ask_tutor", fake_ask_tutor)

    r = client.post("/asdt/negotiate", json={"gap_event_id": gap_id}, headers=_auth_header())
    assert r.status_code == 200, r.text
    negotiation = r.json()
    assert negotiation["decision"] == "accepted_remediation"
    assert negotiation["atdt_citations"]

    r = client.get("/asdt/gaps", params={"course_id": 1}, headers=_auth_header())
    assert r.json()[0]["status"] == "negotiating"

    r = client.get("/asdt/report", params={"course_id": 1}, headers=_auth_header())
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["negotiating_gaps"] == 1
    assert len(report["recent_negotiations"]) == 1

    # A later sync shows the student improved past the threshold: the gap
    # should now resolve itself.
    async def improved_attempts(token, course_id):
        return [
            {
                "id": 2,
                "assessment_id": 2,
                "assessment_title": "Quiz 2",
                "topic": "Graph Traversal",
                "total_score": 85.0,
                "submitted_at": "2026-08-17T00:00:00Z",
            }
        ]

    monkeypatch.setattr(atdt_client, "get_my_attempts", improved_attempts)

    r = client.post("/asdt/sync", json={"course_id": 1}, headers=_auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["resolved_gaps"]) == 1
    assert body["resolved_gaps"][0]["status"] == "resolved"

    r = client.get("/asdt/report", params={"course_id": 1}, headers=_auth_header())
    report = r.json()
    assert report["resolved_gaps"] == 1
    assert report["negotiating_gaps"] == 0
    assert report["overall_mastery"] == 0.85


def test_ask_logs_interaction_and_shows_in_report(client, monkeypatch):
    monkeypatch.setattr(atdt_client, "whoami", _fake_whoami)

    async def fake_ask_tutor(token, course_id, question):
        return {
            "conversation_id": 5,
            "answer": "A binary search tree keeps left < node < right at every node.",
            "citations": [{"source_document": "notes.pdf", "page_number": 1, "excerpt": "..."}],
        }

    monkeypatch.setattr(atdt_client, "ask_tutor", fake_ask_tutor)

    r = client.post(
        "/asdt/ask",
        json={"course_id": 2, "question": "What is a binary search tree?"},
        headers=_auth_header(),
    )
    assert r.status_code == 200, r.text
    interaction = r.json()
    assert interaction["question"] == "What is a binary search tree?"
    assert interaction["atdt_citations"]

    r = client.get("/asdt/report", params={"course_id": 2}, headers=_auth_header())
    assert r.status_code == 200, r.text
    report = r.json()
    assert len(report["recent_interactions"]) == 1
    assert report["recent_interactions"][0]["question"] == "What is a binary search tree?"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_non_student_rejected(client, monkeypatch):
    async def teacher_whoami(token):
        return {"id": 2, "email": "lect@example.com", "full_name": "Dr Test", "role": "lecturer"}

    monkeypatch.setattr(atdt_client, "whoami", teacher_whoami)

    r = client.post("/asdt/sync", json={"course_id": 1}, headers=_auth_header())
    assert r.status_code == 403
