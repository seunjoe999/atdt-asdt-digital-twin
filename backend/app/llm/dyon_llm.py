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

from dyon.core.config import TwinConfig
from dyon.intelligent.agent import build_llm

log = logging.getLogger(__name__)


@lru_cache
def _config() -> TwinConfig:
    # asset_* fields are cosmetic here (they only appear in a system prompt
    # dyon's own DiagnosticAgent would build); TwinConfig still reads every
    # DT_LLM__* value from the environment/.env as usual.
    return TwinConfig(asset_id="atdt", asset_type="course_twin", asset_name="ATDT")


@lru_cache
def _llm():
    return build_llm(_config())


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
