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
import logging
from functools import lru_cache

import json
import re

from dyon.core.config import TwinConfig
from dyon.intelligent.agent import build_llm

log = logging.getLogger(__name__)


@lru_cache
def _config() -> TwinConfig:
    # asset_* fields are cosmetic here (they only appear in a system prompt
    # dyon's own DiagnosticAgent would build); TwinConfig still reads every
    # DT_LLM__* value from the environment/.env as usual.
    return TwinConfig(asset_id="atdt", asset_type="course_twin", asset_name="ATDT")


def _atdt_offline_responder(prompt: str) -> str:
    """A course-aware offline responder (dyon's documented extension point,
    see ``OfflineChatModel``'s docstring).

    The default offline responder just echoes the prompt back, which is fine
    for a generic twin demo but breaks the Examination channel here: its
    prompts require a strict JSON reply, and echoed prose never parses,
    silently producing a zero-question assessment. This responder recognises
    ATDT's own prompt shapes (all defined in app/rag/) and returns a
    minimally valid, clearly-labelled reply for each, so every channel is
    demoable end to end with zero API keys — the offline provider still
    doesn't reason, it just no longer breaks structurally.
    """
    if '"mcqs"' in prompt and '"saqs"' in prompt:
        # Assessment generation (app/rag/assessment_agent.py::generate_questions).
        excerpt = _first_source_sentence(prompt)
        return json.dumps(
            {
                "mcqs": [
                    {
                        "text": f"[offline model — no LLM configured] Which statement best "
                        f"matches the course material? ({excerpt[:80]})",
                        "options": [excerpt[:60] or "Option A", "Option B", "Option C", "Option D"],
                        "correct_answer": excerpt[:60] or "Option A",
                    }
                ],
                "saqs": [
                    {
                        "text": "[offline model — no LLM configured] Explain the concept "
                        "covered in the course material excerpt.",
                        "rubric": "Award full credit for any answer that engages with the "
                        "excerpted material; a real LLM provider is needed for meaningful "
                        "question generation and grading.",
                    }
                ],
            }
        )
    if '"score"' in prompt and '"feedback"' in prompt:
        # SAQ grading (app/rag/assessment_agent.py::grade_saq).
        return json.dumps(
            {
                "score": 0.5,
                "feedback": "[offline model] No language model is configured, so this "
                "response could not be graded against the rubric. Configure DT_LLM__PROVIDER "
                "to get real grading.",
            }
        )
    # Tutoring / Teaching prompts: fall back to an extractive, clearly-labelled
    # answer built from the first retrieved source rather than pure echo.
    excerpt = _first_source_sentence(prompt)
    if excerpt:
        return f"[offline model — no LLM configured] The course material says: {excerpt}"
    return "[offline model] No language model is configured, and no course material was retrieved for this question."


def _first_source_sentence(prompt: str) -> str:
    match = re.search(r"\[Source 1:.*?\]\s*\n(.+)", prompt)
    if not match:
        return ""
    sentence = re.split(r"(?<=[.!?])\s", match.group(1).strip())[0]
    return sentence.strip()


@lru_cache
def _llm():
    config = _config()
    if config.llm.provider == "offline":
        from dyon.intelligent.offline_llm import OfflineChatModel

        return OfflineChatModel(responder=_atdt_offline_responder)
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
