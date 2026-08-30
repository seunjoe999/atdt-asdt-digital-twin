"""Wellbeing channel: check-ins, streak/XP gamification, the counseling
twin's crisis-keyword safety path, and the lecturer's at-risk dashboard.
Uses the offline LLM provider, same as test_smoke.py.
"""


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_student(client, email="wellbeing-student@example.com"):
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "full_name": "A. Student", "role": "student"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_checkins_and_streak(client):
    token = _register_student(client)
    headers = _auth_header(token)

    r = client.post("/wellbeing/checkin", json={"mood": 4, "stress": 2, "note": "feeling good"}, headers=headers)
    assert r.status_code == 201, r.text

    r = client.post("/wellbeing/checkin", json={"mood": 3, "stress": 3, "note": ""}, headers=headers)
    assert r.status_code == 201, r.text

    r = client.get("/wellbeing/checkins", headers=headers)
    assert r.status_code == 200, r.text
    checkins = r.json()
    assert len(checkins) == 2

    r = client.get("/wellbeing/streak", headers=headers)
    assert r.status_code == 200, r.text
    streak = r.json()
    assert streak["current_streak"] >= 1
    assert streak["xp"] >= 20


def test_counsel_normal_message(client):
    token = _register_student(client, email="student2@example.com")
    headers = _auth_header(token)

    r = client.post("/wellbeing/counsel", json={"message": "I'm nervous about my exam tomorrow."}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"]
    assert body["flagged"] is False
    assert body["resources"] == []


def test_counsel_crisis_message_is_flagged(client):
    token = _register_student(client, email="student3@example.com")
    headers = _auth_header(token)

    r = client.post("/wellbeing/counsel", json={"message": "I want to end my life"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flagged"] is True
    assert len(body["resources"]) > 0

    r = client.get("/wellbeing/counsel/history", headers=headers)
    assert r.status_code == 200, r.text
    history = r.json()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_at_risk_dashboard(client):
    r = client.post(
        "/auth/register",
        json={"email": "lecturer2@example.com", "password": "password123", "full_name": "Dr. Bello", "role": "lecturer"},
    )
    assert r.status_code == 201, r.text
    lecturer_token = r.json()["access_token"]

    student_token = _register_student(client, email="student4@example.com")

    r = client.post(
        "/courses",
        json={"title": "Physics", "description": "", "subject_area": "Sci"},
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 201, r.text
    course = r.json()
    code = course["enrolment_code"]

    r = client.post("/courses/enrol", json={"enrolment_code": code}, headers=_auth_header(student_token))
    assert r.status_code == 200, r.text

    r = client.post(
        "/wellbeing/checkin", json={"mood": 2, "stress": 4, "note": ""}, headers=_auth_header(student_token)
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/courses/{course['id']}/wellbeing", headers=_auth_header(lecturer_token))
    assert r.status_code == 200, r.text
    at_risk = r.json()
    assert len(at_risk) == 1
    entry = at_risk[0]
    assert "risk_score" in entry
    assert "risk_label" in entry
    assert entry["student_id"]
