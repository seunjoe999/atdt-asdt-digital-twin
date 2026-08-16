"""End-to-end smoke test covering all three channels, using the offline LLM
provider so it needs no API key and no network. Run with:

    pytest -q
"""

import io
import time


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_full_flow(client):
    # Register a lecturer and a student.
    r = client.post(
        "/auth/register",
        json={
            "email": "lecturer@example.com",
            "password": "password123",
            "full_name": "Dr. Fashina",
            "role": "lecturer",
        },
    )
    assert r.status_code == 201, r.text
    lecturer_token = r.json()["access_token"]

    r = client.post(
        "/auth/register",
        json={
            "email": "student@example.com",
            "password": "password123",
            "full_name": "A. Student",
            "role": "student",
        },
    )
    assert r.status_code == 201, r.text
    student_token = r.json()["access_token"]

    # Lecturer creates a course.
    r = client.post(
        "/courses",
        json={"title": "Data Structures", "description": "", "subject_area": "CS"},
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 201, r.text
    course = r.json()
    course_id = course["id"]
    code = course["enrolment_code"]

    # Lecturer uploads a plain-text document.
    content = (
        b"A binary search tree (BST) is a node-based binary tree where each "
        b"node's left subtree contains only values less than the node, and the "
        b"right subtree contains only values greater than the node. Searching "
        b"a balanced BST takes O(log n) time."
    )
    r = client.post(
        f"/courses/{course_id}/documents",
        files={"file": ("notes.txt", io.BytesIO(content), "text/plain")},
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 201, r.text
    document_id = r.json()["id"]

    # Ingestion runs as a FastAPI background task; poll briefly for completion.
    for _ in range(20):
        r = client.get(f"/courses/{course_id}/documents", headers=_auth_header(lecturer_token))
        doc = next(d for d in r.json() if d["id"] == document_id)
        if doc["status"] != "processing":
            break
        time.sleep(0.25)
    assert doc["status"] == "ready", doc

    # Student enrols using the code.
    r = client.post(
        "/courses/enrol", json={"enrolment_code": code}, headers=_auth_header(student_token)
    )
    assert r.status_code == 200, r.text

    # Student asks the Tutoring Channel a question; offline LLM still returns
    # a response and the retrieval step still returns citations.
    r = client.post(
        f"/courses/{course_id}/tutoring/query",
        json={"question": "What is a binary search tree?"},
        headers=_auth_header(student_token),
    )
    assert r.status_code == 200, r.text
    tutor_answer = r.json()
    assert tutor_answer["answer"]
    assert isinstance(tutor_answer["citations"], list)

    # Lecturer generates a teaching material.
    r = client.post(
        f"/courses/{course_id}/teaching/materials",
        json={"type": "summary", "topic": "binary search trees", "instructions": ""},
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 201, r.text

    # Lecturer generates, reviews, and publishes an assessment.
    r = client.post(
        f"/courses/{course_id}/examination/assessments",
        json={"title": "Quiz 1", "topic": "binary search trees", "mcq_count": 2, "saq_count": 1},
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 201, r.text
    assessment_id = r.json()["id"]

    r = client.get(
        f"/courses/{course_id}/examination/assessments/{assessment_id}/review",
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/courses/{course_id}/examination/assessments/{assessment_id}/publish",
        headers=_auth_header(lecturer_token),
    )
    assert r.status_code == 200, r.text

    # Student takes and submits the assessment.
    r = client.get(
        f"/courses/{course_id}/examination/assessments/{assessment_id}/take",
        headers=_auth_header(student_token),
    )
    assert r.status_code == 200, r.text
    questions = r.json()

    answers = []
    for q in questions:
        if q["type"] == "mcq":
            answers.append({"question_id": q["id"], "answer": q["options"][0] if q["options"] else ""})
        else:
            answers.append({"question_id": q["id"], "answer": "A binary tree ordered by key."})

    r = client.post(
        f"/courses/{course_id}/examination/assessments/{assessment_id}/submit",
        json={"answers": answers},
        headers=_auth_header(student_token),
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["total_score"] is not None
    assert len(result["responses"]) == len(questions)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
