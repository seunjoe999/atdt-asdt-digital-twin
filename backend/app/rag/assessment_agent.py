"""Examination Channel: AI-assisted question generation and SAQ grading
(thesis Chapter 3.6 — Generate -> ValidateOutput -> retry up to 3 times).
"""

from __future__ import annotations

import json
import logging
import re

from app.llm.dyon_llm import generate
from app.rag.agent import _build_context, retrieve

log = logging.getLogger(__name__)

MAX_RETRIES = 3


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _validate(payload: dict, mcq_count: int, saq_count: int) -> bool:
    if not isinstance(payload, dict):
        return False
    mcqs = payload.get("mcqs", [])
    saqs = payload.get("saqs", [])
    if not isinstance(mcqs, list) or not isinstance(saqs, list):
        return False
    if len(mcqs) < 1 and mcq_count > 0:
        return False
    if len(saqs) < 1 and saq_count > 0:
        return False
    for q in mcqs:
        if not isinstance(q, dict):
            return False
        if "text" not in q or "options" not in q or "correct_answer" not in q:
            return False
        if not isinstance(q["options"], list) or len(q["options"]) != 4:
            return False
        if q["correct_answer"] not in q["options"]:
            return False
    for q in saqs:
        if not isinstance(q, dict) or "text" not in q or "rubric" not in q:
            return False
    return True


async def generate_questions(
    *, collection_name: str, topic: str, mcq_count: int, saq_count: int
) -> dict:
    """Returns {"mcqs": [...], "saqs": [...]}, validated and retried up to
    MAX_RETRIES times on structurally malformed output.
    """
    query = topic or "key assessable concepts across the course"
    chunks = retrieve(collection_name, query, k=10)
    context = _build_context(chunks)

    system_prompt = (
        "You are an assessment-design agent generating exam questions strictly "
        "grounded in the course material excerpts below. Respond with ONLY a JSON "
        "object, no prose, no markdown fences, matching exactly this shape:\n"
        '{"mcqs": [{"text": "...", "options": ["A", "B", "C", "D"], '
        '"correct_answer": "<one of the 4 options, verbatim>"}], '
        '"saqs": [{"text": "...", "rubric": "<what a full-credit answer must cover>"}]}\n\n'
        f"Generate exactly {mcq_count} MCQs and {saq_count} SAQs.\n\n"
        f"COURSE MATERIAL:\n{context}"
    )
    user_prompt = f"Topic: {topic or '(cover the material broadly)'}"

    last_payload: dict | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        raw = await generate(system_prompt, user_prompt)
        payload = _extract_json(raw)
        if payload and _validate(payload, mcq_count, saq_count):
            return payload
        last_payload = payload
        log.warning("Assessment generation attempt %d/%d failed validation", attempt, MAX_RETRIES)

    # Exhausted retries: return whatever we have (possibly empty) rather than
    # raising, so the lecturer sees a reviewable (if incomplete) draft instead
    # of a hard failure.
    return last_payload or {"mcqs": [], "saqs": []}


async def grade_saq(*, question_text: str, rubric: str, student_answer: str) -> tuple[float, str]:
    """LLM-based SAQ evaluation against a rubric. Returns (score 0-1, feedback)."""
    system_prompt = (
        "You are grading a student's short-answer response against a rubric. "
        "Respond with ONLY JSON: "
        '{"score": <float 0.0-1.0>, "feedback": "<question-level feedback for the student>"}'
    )
    user_prompt = (
        f"Question: {question_text}\nRubric: {rubric}\nStudent answer: {student_answer}"
    )
    raw = await generate(system_prompt, user_prompt)
    payload = _extract_json(raw)
    if not payload or "score" not in payload:
        return 0.0, "Automated grading failed to parse a score; please review manually."
    try:
        score = max(0.0, min(1.0, float(payload["score"])))
    except (TypeError, ValueError):
        score = 0.0
    feedback = str(payload.get("feedback", ""))
    return score, feedback
