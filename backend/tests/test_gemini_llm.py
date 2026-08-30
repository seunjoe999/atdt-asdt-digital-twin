"""Gemini isn't a provider dyon (v0.11) ships natively — app/llm/dyon_llm.py
bypasses dyon's build_llm for this one provider and points ChatOpenAI at
Google's OpenAI-compatible endpoint directly. This locks that wiring down
without touching the module's lru_cache'd singletons (conftest pins the
whole test process to DT_LLM__PROVIDER=offline).
"""

from dyon.core.config import TwinConfig

from app.llm.dyon_llm import _GEMINI_OPENAI_BASE_URL, _build_gemini_llm


def test_gemini_uses_openai_compatible_endpoint():
    config = TwinConfig(asset_id="t", asset_type="t", asset_name="t")
    config.llm.provider = "gemini"
    config.llm.api_key = "test-key"

    llm = _build_gemini_llm(config)

    assert llm.model_name == "gemini-2.0-flash"
    assert str(llm.openai_api_base) == _GEMINI_OPENAI_BASE_URL


def test_gemini_respects_custom_model_and_base_url():
    config = TwinConfig(asset_id="t", asset_type="t", asset_name="t")
    config.llm.provider = "gemini"
    config.llm.api_key = "test-key"
    config.llm.model = "gemini-1.5-pro"
    config.llm.base_url = "https://example.com/openai/"

    llm = _build_gemini_llm(config)

    assert llm.model_name == "gemini-1.5-pro"
    assert str(llm.openai_api_base) == "https://example.com/openai/"
