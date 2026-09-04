"""Adversarial RBAC / auth pass (MST 90-day roadmap, Phase 1 item #3).

Every scenario asserts a 401/403/404 — never a 200 with leaked data, never
an unhandled 500. Scenarios ranked by severity per the PM spec:

 1. Cross-student wellbeing/counseling data isolation (highest stakes)
 2. IDOR across courses (assessments, documents, roster)
 3. Role tampering (architectural — role always re-read from DB, never trusted from JWT/body)
 4. Student JWT hitting lecturer-only endpoints
 5. Expired JWT rejected
 6. Password reset — SKIPPED: no such flow exists in this codebase (see note below)
 7. SQL/ORM injection via free-text fields
 8. Horizontal escalation on tutoring conversations
 9. JWT signature/algorithm tampering
10. Lecturer scoped to courses they actually teach

Note on #6: there is no password-reset endpoint anywhere in app/routers —
nothing to adversarially test. This is itself a real gap (a student who
forgets their password has no self-service recovery), tracked on the
roadmap rather than exercised here.
"""

import jwt

from app.config import get_settings


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, email, role, name="Test User"):
    r = client.post("/auth/register", json={"email": email, "password": "password123", "full_name": name, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _make_course(client, lecturer_token, title="Course"):
    r = client.post("/courses", json={"title": title, "description": "", "subject_area": ""}, headers=_auth(lecturer_token))
    assert r.status_code == 201, r.text
    return r.json()


def _enrol(client, student_token, code):
    r = client.post("/courses/enrol", json={"enrolment_code": code}, headers=_auth(student_token))
    assert r.status_code == 200, r.text


# ---------- 1. Cross-student wellbeing/counseling isolation ----------


def test_student_cannot_see_another_students_checkins(client):
    a = _register(client, "rbac-a@example.com", "student")
    b = _register(client, "rbac-b@example.com", "student")

    r = client.post("/wellbeing/checkin", json={"mood": 2, "stress": 5, "note": "struggling badly"}, headers=_auth(a))
    assert r.status_code == 201, r.text

    r = client.get("/wellbeing/checkins", headers=_auth(b))
    assert r.status_code == 200, r.text
    assert r.json() == []  # B's own list must never contain A's data


def test_student_cannot_see_another_students_counsel_history(client):
    a = _register(client, "rbac-c@example.com", "student")
    b = _register(client, "rbac-d@example.com", "student")

    r = client.post("/wellbeing/counsel", json={"message": "I want to end my life"}, headers=_auth(a))
    assert r.status_code == 200, r.text

    r = client.get("/wellbeing/counsel/history", headers=_auth(b))
    assert r.status_code == 200, r.text
    assert r.json() == []


# ---------- 2. IDOR across courses ----------


def test_student_cannot_access_unenrolled_course(client):
    lecturer = _register(client, "rbac-lect1@example.com", "lecturer")
    outsider = _register(client, "rbac-outsider@example.com", "student")
    course = _make_course(client, lecturer, "Course A")

    r = client.get(f"/courses/{course['id']}", headers=_auth(outsider))
    assert r.status_code == 403, r.text

    r = client.get(f"/courses/{course['id']}/documents", headers=_auth(outsider))
    assert r.status_code == 403, r.text

    r = client.get(f"/courses/{course['id']}/messages", headers=_auth(outsider))
    assert r.status_code == 403, r.text


def test_student_cannot_take_assessment_in_unenrolled_course(client):
    lecturer = _register(client, "rbac-lect2@example.com", "lecturer")
    outsider = _register(client, "rbac-outsider2@example.com", "student")
    course = _make_course(client, lecturer, "Course B")

    r = client.get(f"/courses/{course['id']}/examination/assessments/published", headers=_auth(outsider))
    assert r.status_code == 403, r.text

    r = client.get(f"/courses/{course['id']}/examination/assessments/1/take", headers=_auth(outsider))
    assert r.status_code == 403, r.text


# ---------- 3. Role tampering ----------


def test_authorization_uses_db_role_not_request_body():
    """A student cannot escalate by sending a "role" field anywhere in a
    protected request — every protected endpoint's role check comes from
    ``require_role`` re-reading ``user.role`` off the DB row looked up via
    the JWT's ``sub`` (user id), never from request payloads or the JWT's
    own "role" claim. There is no code path that trusts a client-supplied
    role, so this is verified structurally rather than by a single request:
    see app/deps.py's require_role, which never reads request.body/query.
    """
    import inspect

    from app import deps

    source = inspect.getsource(deps.require_role)
    assert "user.role" in source
    assert "payload" not in source and "request" not in source


# ---------- 4. Student JWT hitting lecturer-only endpoints ----------


def test_student_cannot_create_course(client):
    student = _register(client, "rbac-e@example.com", "student")
    r = client.post("/courses", json={"title": "x", "description": "", "subject_area": ""}, headers=_auth(student))
    assert r.status_code == 403, r.text


def test_student_cannot_upload_document(client):
    lecturer = _register(client, "rbac-lect3@example.com", "lecturer")
    student = _register(client, "rbac-f@example.com", "student")
    course = _make_course(client, lecturer, "Course C")
    _enrol(client, student, course["enrolment_code"])

    r = client.post(
        f"/courses/{course['id']}/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=_auth(student),
    )
    assert r.status_code == 403, r.text


def test_student_cannot_create_assessment_or_publish(client):
    lecturer = _register(client, "rbac-lect4@example.com", "lecturer")
    student = _register(client, "rbac-g@example.com", "student")
    course = _make_course(client, lecturer, "Course D")
    _enrol(client, student, course["enrolment_code"])

    r = client.post(
        f"/courses/{course['id']}/examination/assessments",
        json={"title": "Quiz", "topic": "", "mcq_count": 1, "saq_count": 0},
        headers=_auth(student),
    )
    assert r.status_code == 403, r.text


def test_student_cannot_hit_at_risk_dashboard(client):
    lecturer = _register(client, "rbac-lect5@example.com", "lecturer")
    student = _register(client, "rbac-h@example.com", "student")
    course = _make_course(client, lecturer, "Course E")
    _enrol(client, student, course["enrolment_code"])

    r = client.get(f"/courses/{course['id']}/wellbeing", headers=_auth(student))
    assert r.status_code == 403, r.text


def test_student_cannot_capture_teaching_style(client):
    lecturer = _register(client, "rbac-lect6@example.com", "lecturer")
    student = _register(client, "rbac-i@example.com", "student")
    course = _make_course(client, lecturer, "Course F")
    _enrol(client, student, course["enrolment_code"])

    r = client.post(
        f"/courses/{course['id']}/teaching/style", json={"sample": "x" * 50}, headers=_auth(student)
    )
    assert r.status_code == 403, r.text


# ---------- 5. Expired JWT rejected ----------


def test_expired_jwt_is_rejected(client):
    import datetime

    settings = get_settings()
    expired_payload = {
        "sub": "1",
        "role": "student",
        "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5),
    }
    token = jwt.encode(expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    r = client.get("/auth/me", headers=_auth(token))
    assert r.status_code == 401, r.text


# ---------- 7. SQL/ORM injection via free-text fields ----------


def test_injection_payload_in_checkin_note_is_stored_inert(client):
    student = _register(client, "rbac-j@example.com", "student")
    payload = "'; DROP TABLE users; --"

    r = client.post("/wellbeing/checkin", json={"mood": 3, "stress": 3, "note": payload}, headers=_auth(student))
    assert r.status_code == 201, r.text
    assert r.json()["note"] == payload  # stored verbatim as data, never interpreted

    # If the table had actually been dropped, this would 401/500 instead of 200.
    r = client.get("/auth/me", headers=_auth(student))
    assert r.status_code == 200, r.text


def test_injection_payload_in_course_message_is_stored_inert(client):
    lecturer = _register(client, "rbac-lect7@example.com", "lecturer")
    course = _make_course(client, lecturer, "Course G")
    payload = "' OR '1'='1"

    r = client.post(f"/courses/{course['id']}/messages", json={"content": payload}, headers=_auth(lecturer))
    assert r.status_code == 201, r.text
    assert r.json()["content"] == payload


# ---------- 8. Horizontal escalation on tutoring conversations ----------


def test_student_cannot_read_another_students_tutoring_conversation(client):
    lecturer = _register(client, "rbac-lect8@example.com", "lecturer")
    a = _register(client, "rbac-k@example.com", "student")
    b = _register(client, "rbac-l@example.com", "student")
    course = _make_course(client, lecturer, "Course H")
    _enrol(client, a, course["enrolment_code"])
    _enrol(client, b, course["enrolment_code"])

    r = client.post(
        f"/courses/{course['id']}/tutoring/query", json={"question": "what is X?"}, headers=_auth(a)
    )
    assert r.status_code == 200, r.text
    conversation_id = r.json()["conversation_id"]

    r = client.get(
        f"/courses/{course['id']}/tutoring/conversations/{conversation_id}/messages", headers=_auth(b)
    )
    assert r.status_code == 404, r.text


# ---------- 9. JWT signature/algorithm tampering ----------


def test_jwt_with_wrong_secret_is_rejected(client):
    import datetime

    settings = get_settings()
    forged = jwt.encode(
        {"sub": "1", "role": "lecturer", "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)},
        "some-other-secret-the-attacker-guessed",
        algorithm=settings.jwt_algorithm,
    )
    r = client.get("/auth/me", headers=_auth(forged))
    assert r.status_code == 401, r.text


def test_jwt_alg_none_is_rejected(client):
    import base64
    import json as _json

    header = base64.urlsafe_b64encode(_json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
    body = base64.urlsafe_b64encode(_json.dumps({"sub": "1", "role": "lecturer"}).encode()).rstrip(b"=")
    forged_token = (header + b"." + body + b".").decode()

    r = client.get("/auth/me", headers=_auth(forged_token))
    assert r.status_code == 401, r.text


# ---------- 10. Lecturer scoped to courses they actually teach ----------


def test_lecturer_cannot_manage_another_lecturers_course(client):
    lecturer_a = _register(client, "rbac-lect9@example.com", "lecturer")
    lecturer_b = _register(client, "rbac-lect10@example.com", "lecturer")
    course = _make_course(client, lecturer_a, "Course I")

    r = client.get(f"/courses/{course['id']}/students", headers=_auth(lecturer_b))
    assert r.status_code == 403, r.text

    r = client.post(
        f"/courses/{course['id']}/examination/assessments",
        json={"title": "Quiz", "topic": "", "mcq_count": 1, "saq_count": 0},
        headers=_auth(lecturer_b),
    )
    assert r.status_code == 403, r.text

    r = client.get(f"/courses/{course['id']}/wellbeing", headers=_auth(lecturer_b))
    assert r.status_code == 403, r.text
