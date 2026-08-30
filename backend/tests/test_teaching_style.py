"""Teaching Style Twin: the lecturer pastes a teaching sample, ATDT distills
a style profile, and the profile is reused as a persona suffix in materials
and advice generation. Uses the offline LLM provider, same as test_smoke.py.
"""


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, email, role, full_name):
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "full_name": full_name, "role": role},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _make_course(client, lecturer_token):
    r = client.post(
        "/courses",
        json={"title": "Signals & Systems", "description": "", "subject_area": "EE"},
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_style_capture_and_get(client):
    lecturer_token = _register(client, "style-lecturer@example.com", "lecturer", "Dr. Style")
    course = _make_course(client, lecturer_token)

    r = client.get(f"/courses/{course['id']}/teaching/style", headers=_auth_header(lecturer_token))
    assert r.status_code == 200, r.text
    assert r.json()["has_profile"] is False

    sample = (
        "Alright everyone, let's think about this like a leaky bucket for a second. "
        "So — quick check, does that make sense so far? Great, let's keep going."
    )
    r = client.post(
        f"/courses/{course['id']}/teaching/style", json={"sample": sample}, headers=_auth_header(lecturer_token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_profile"] is True
    assert body["style_summary"]

    r = client.get(f"/courses/{course['id']}/teaching/style", headers=_auth_header(lecturer_token))
    assert r.status_code == 200, r.text
    assert r.json()["has_profile"] is True
    assert r.json()["style_summary"] == body["style_summary"]


def test_style_requires_lecturer(client):
    lecturer_token = _register(client, "style-lecturer2@example.com", "lecturer", "Dr. Style2")
    course = _make_course(client, lecturer_token)
    student_token = _register(client, "style-student@example.com", "student", "A. Student")

    r = client.post(
        f"/courses/{course['id']}/teaching/style",
        json={"sample": "x" * 50},
        headers=_auth_header(student_token),
    )
    assert r.status_code in (403, 404)
