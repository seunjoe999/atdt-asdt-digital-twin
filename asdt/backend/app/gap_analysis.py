"""Simulation Layer + Analytics/Monitoring Layer (thesis Layers 2-3):
turn a student's raw ATDT attempt history into a per-topic mastery model,
and score which topics are gaps worth negotiating remediation for.
"""

from __future__ import annotations

from collections import defaultdict

from app.config import get_settings


def compute_mastery_by_topic(attempts: list[dict]) -> dict[str, tuple[float, int]]:
    """attempts: ATDT's MyAttemptOut list (topic, total_score 0-100).
    Returns {topic: (mastery 0-1, sample_count)}, averaging every submitted
    attempt's score per topic. Untitled/blank topics are skipped — they
    can't be tied to a curriculum gap.
    """
    buckets: dict[str, list[float]] = defaultdict(list)
    for attempt in attempts:
        topic = (attempt.get("topic") or "").strip()
        score = attempt.get("total_score")
        if not topic or score is None:
            continue
        buckets[topic].append(score / 100.0)

    return {topic: (sum(scores) / len(scores), len(scores)) for topic, scores in buckets.items()}


def is_gap(mastery: float) -> bool:
    return mastery < get_settings().gap_threshold


def severity(mastery: float) -> float:
    return round(max(0.0, 1.0 - mastery), 4)
