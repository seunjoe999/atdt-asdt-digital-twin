"""The Agent Orchestrator's LLM client, supplied by the dyon framework.

Chapter 3.5 of the ATDT thesis describes an "Agent Orchestrator" that
coordinates prompt construction, LLM calls, and response parsing for the
Teaching, Tutoring, and Examination channels. That role is filled here by
``dyon.core.config.TwinConfig`` (provider-agnostic LLM configuration, read
from the ``DT_LLM__*`` environment variables) and
``dyon.intelligent.agent.build_llm`` (the factory that turns that config into
a ready LangChain chat model — OpenAI, Anthropic, Ollama, or a dependency-free
offline model for demos without an API key).

Every channel in this codebase calls :func:`generate` rather than talking to
an LLM SDK directly, so swapping providers is a ``.env`` change, never a code
change — the same guarantee dyon makes for a physical asset twin's diagnostic
agent applies here to a course twin's teaching/tutoring/examination agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from functools import lru_cache

from dyon.core.config import TwinConfig
from dyon.intelligent.agent import build_llm

log = logging.getLogger(__name__)


@lru_cache
def _config() -> TwinConfig:
    # asset_* fields are cosmetic here (they only appear in a system prompt
    # dyon's own DiagnosticAgent would build); TwinConfig still reads every
    # DT_LLM__* value from the environment/.env as usual.
    return TwinConfig(asset_id="atdt", asset_type="course_twin", asset_name="ATDT")


# ---------------------------------------------------------------------------
# Offline responder: a lightweight extractive engine, not a language model.
#
# The point of "offline" is to demo the whole app with zero API key and zero
# network. A responder that just echoes the prompt (dyon's default) makes
# every channel look broken — Teaching/Tutoring answers with unhelpful
# boilerplate, and Examination silently produces zero questions because
# echoed prose never parses as JSON. This version actually reads the
# retrieved course material and picks the sentences most relevant to the
# question/topic by keyword overlap, so the demo is grounded and coherent
# even with no model behind it. It is deliberately labelled "Demo mode" in
# the UI rather than "no LLM configured" — it does work, it just doesn't
# reason.
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "what", "which", "who", "whom",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
    "and", "or", "but", "if", "then", "so", "of", "to", "in", "on", "for", "with",
    "as", "by", "at", "from", "about", "into", "through", "during", "how", "why",
    "when", "where", "can", "could", "should", "would", "do", "does", "did", "explain",
    "describe", "tell", "me", "please", "my", "your", "their", "its", "be", "been",
    "being", "not", "no", "yes", "more", "most", "some", "any", "all", "each",
    "other", "such", "only", "just", "also", "topic", "course", "material", "student",
    "question", "concept", "covered", "excerpt",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z']+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _split_sentences(text: str) -> list[str]:
    # Drop "[Source N: doc, page P]" citation headers before splitting, or
    # they get picked up as sentences and leak into answers/options.
    text = re.sub(r"\[Source \d+:[^\]]*\]", " ", text)
    flat = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if len(s.strip()) > 15]


def _rank_sentences(context: str, query: str) -> list[str]:
    """All course-material sentences, best keyword match to `query` first."""
    sentences = _split_sentences(context)
    if not sentences:
        return []
    q_words = _words(query)
    if not q_words:
        return sentences
    scored = [(len(_words(s) & q_words), i, s) for i, s in enumerate(sentences)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    # Keep original order among equally-scored sentences that DID match;
    # sentences with zero overlap are still returned (as a fallback tail) so
    # callers always have enough material to work with.
    return [s for _, _, s in scored]


def _extract_context(prompt: str) -> str:
    match = re.search(r"COURSE MATERIAL:\s*\n(.*)", prompt, re.DOTALL)
    if not match:
        return ""
    context = match.group(1)
    # The flattened prompt is "<system>\n\n<human>" and the system message is
    # everything from COURSE MATERIAL: onward, so this capture also swallows
    # the trailing human-message fields (Topic/Student question/Additional
    # instructions). Cut them off — they're prompt scaffolding, not material.
    boundary = re.search(r"\n(Topic|Student question|Additional instructions):", context)
    return context[: boundary.start()] if boundary else context


def _extract_field(prompt: str, *labels: str) -> str:
    for label in labels:
        match = re.search(rf"{label}:\s*(.+)", prompt)
        if match:
            return match.group(1).split("\n")[0].strip()
    return ""


def _demo_answer(prompt: str) -> str:
    context = _extract_context(prompt)
    is_material = "Additional instructions:" in prompt  # generate_teaching_material's user_prompt shape
    query = _extract_field(prompt, "Student question", "Topic") or prompt[-200:]
    ranked = _rank_sentences(context, query)
    if not ranked:
        return (
            "[Demo mode] No course material has been ingested for this topic yet, so there's "
            "nothing to ground an answer in. Upload course material first."
        )
    if is_material:
        bullets = "\n".join(f"- {s}" for s in ranked[:6])
        return f"[Demo mode — grounded in your uploaded course material]\n{bullets}"
    best = ranked[:3]
    return "[Demo mode — grounded in your uploaded course material]\n" + " ".join(best)


def _truncate(text: str, limit: int) -> str:
    text = text.rstrip(".")
    return text[:limit].rstrip() + "..." if len(text) > limit else text


def _make_mcq(sentence: str, distractors: list[str]) -> dict:
    correct = _truncate(sentence, 140)
    pool = [_truncate(d, 140) for d in distractors if d != sentence]
    options = [correct] + pool[:3]
    while len(options) < 4:
        options.append(f"None of the other statements (distractor {len(options)})")
    return {
        "text": "Which of the following is accurate, based on the course material?",
        "options": options,
        "correct_answer": correct,
    }


def _make_saq(sentence: str) -> dict:
    snippet = _truncate(sentence, 160)
    return {
        "text": f"Explain, in your own words, the following idea from the course material and why it matters: “{snippet}”",
        "rubric": f"Full credit requires the answer to correctly restate and explain: {sentence}",
    }


def _demo_assessment(prompt: str) -> str:
    counts = re.search(r"Generate exactly (\d+) MCQs and (\d+) SAQs", prompt)
    mcq_count = int(counts.group(1)) if counts else 1
    saq_count = int(counts.group(2)) if counts else 1

    context = _extract_context(prompt)
    topic = _extract_field(prompt, "Topic")
    ranked = _rank_sentences(context, topic) or _split_sentences(context)

    if not ranked:
        # No material at all: still return a structurally valid, clearly
        # labelled draft rather than an empty assessment.
        filler = "No course material has been ingested yet for this topic."
        ranked = [filler]

    # Cycle through ranked sentences so consecutive questions don't repeat
    # the same fact when there are fewer sentences than requested questions.
    def pick(i: int) -> str:
        return ranked[i % len(ranked)]

    mcqs = [_make_mcq(pick(i), ranked) for i in range(mcq_count)]
    saqs = [_make_saq(pick(mcq_count + i)) for i in range(saq_count)]
    return json.dumps({"mcqs": mcqs, "saqs": saqs})


def _demo_grade(prompt: str) -> str:
    rubric = _extract_field(prompt, "Rubric")
    answer = _extract_field(prompt, "Student answer")
    rubric_words = _words(rubric)
    answer_words = _words(answer)
    if not rubric_words:
        score = 0.5
    else:
        overlap = len(rubric_words & answer_words)
        score = round(min(1.0, overlap / max(3, len(rubric_words) * 0.4)), 2)
    if score >= 0.7:
        feedback = "[Demo mode] Your answer covers most of the key terms the rubric expects. Good work."
    elif score >= 0.3:
        feedback = "[Demo mode] Your answer touches on part of what the rubric expects, but is missing some key ideas."
    else:
        feedback = "[Demo mode] Your answer doesn't yet mention the key ideas the rubric expects — review the material and try again."
    return json.dumps({"score": score, "feedback": feedback})


def _demo_counsel(prompt: str) -> str:
    """The counseling channel has no course material to ground answers in —
    ``_demo_answer``'s "no course material ingested" fallback is wrong here,
    so it gets its own canned-but-warm response instead."""
    crisis = "may be in crisis" in prompt
    if crisis:
        return (
            "[Demo mode] I hear you, and I'm really glad you told me this. What you're feeling "
            "matters, and you don't have to carry it alone. Please reach out to a trusted adult, "
            "your school counselor, or a crisis service right now — I'll stay right here with you "
            "in the meantime."
        )
    student_message = prompt.rsplit("\n\n", 1)[-1].strip()
    topic = (student_message[:120].rstrip(".") or "how you're doing").lower()
    return (
        f"[Demo mode] Thanks for sharing that — it sounds like {topic} has been on your mind. "
        "That's completely understandable, and it's worth taking seriously rather than pushing "
        "through alone. One small next step: could you tell me one specific thing about it that's "
        "weighing on you most right now?"
    )


def _demo_style(prompt: str) -> str:
    """No course material, no rubric — just a few generic-but-plausible
    style bullets so the "observe the teacher" feature is demoable offline
    without a real LLM doing the reading."""
    return (
        "[Demo mode] Style notes (a real LLM would read your sample far more closely):\n"
        "- Tone: conversational and encouraging, not overly formal\n"
        "- Pacing: introduces one idea at a time before moving on\n"
        "- Examples: leans on everyday analogies to make abstract ideas concrete\n"
        "- Handling confusion: rephrases rather than just repeating the same explanation\n"
        "- Verbal habit: frequently checks understanding before moving forward"
    )


def _atdt_offline_responder(prompt: str) -> str:
    """A course-aware offline responder (dyon's documented extension point,
    see ``OfflineChatModel``'s docstring): recognises ATDT's own prompt
    shapes (all defined in app/rag/) and returns a grounded, structurally
    valid reply for each, so every channel is demoable end to end with zero
    API keys and zero network calls.
    """
    if "teaching-style analyst" in prompt.lower():
        return _demo_style(prompt)
    if "counselor twin" in prompt.lower():
        return _demo_counsel(prompt)
    if '"mcqs"' in prompt and '"saqs"' in prompt:
        return _demo_assessment(prompt)
    if '"score"' in prompt and '"feedback"' in prompt:
        return _demo_grade(prompt)
    return _demo_answer(prompt)


_GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _build_gemini_llm(config: TwinConfig):
    # dyon (v0.11) only ships OpenAI/Anthropic/Ollama/offline — Gemini has no
    # first-class support there. Google exposes an OpenAI-compatible endpoint
    # though, so we bypass dyon's build_llm for this one provider and
    # construct ChatOpenAI directly, pointed at that endpoint. Every other
    # provider still goes through dyon unchanged.
    from langchain_openai import ChatOpenAI

    # LLMConfig.model defaults to "gpt-4o-mini" (dyon's OpenAI default), which
    # isn't empty — so a plain `or` fallback never fires and DT_LLM__MODEL
    # left unset would silently send an OpenAI model name to Gemini's
    # endpoint. Only trust an explicit "gemini*" model; anything else falls
    # back to a sane Gemini default.
    model = config.llm.model if config.llm.model.startswith("gemini") else "gemini-2.0-flash"

    return ChatOpenAI(
        model=model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url or _GEMINI_OPENAI_BASE_URL,
        temperature=config.llm.temperature,
        timeout=config.llm.timeout_s,
        max_retries=config.llm.max_retries,
        max_tokens=config.llm.max_tokens,
    )


@lru_cache
def _llm():
    config = _config()
    if config.llm.provider == "offline":
        from dyon.intelligent.offline_llm import OfflineChatModel

        return OfflineChatModel(responder=_atdt_offline_responder)
    if config.llm.provider == "gemini":
        return _build_gemini_llm(config)
    return build_llm(config)


async def generate(system_prompt: str, user_prompt: str) -> str:
    """Run one system+user prompt through the configured LLM and return text."""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _llm()
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

    try:
        deadline = _config().llm.timeout_s * 2
        result = await asyncio.wait_for(llm.ainvoke(messages), timeout=deadline)
        content = result.content
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return str(content)
    except TimeoutError:
        log.error("LLM call timed out")
        return "[error] The language model timed out. Please try again."
    except Exception as exc:  # provider errors, auth errors, etc.
        log.error("LLM call failed: %s", exc)
        return f"[error] The language model call failed: {exc}"


def provider_name() -> str:
    return _config().llm.provider
