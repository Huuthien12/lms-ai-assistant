from pathlib import Path

import pytest

from backend.services.ai.demo_chat_provider import build_demo_chat_orchestrator
from backend.services.ai.deeptutor_provider import DeepTutorProvider
from backend.services.ai.fallback_provider import FallbackAIProvider
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.demo_runtime_config import cors_origins


def test_groq_chat_is_primary_with_ollama_fallback_only():
    result = build_demo_chat_orchestrator(Path("."), {"DEMO_CHAT_PROVIDER": "groq", "DEMO_CHAT_FALLBACK": "ollama"})
    assert isinstance(result.default_provider, FallbackAIProvider)
    assert isinstance(result.default_provider.primary_provider, DeepTutorProvider)
    assert isinstance(result.default_provider.fallback_provider, OllamaProvider)
    assert result.default_provider.primary_provider.provider == "groq"


def test_invalid_demo_provider_or_timeout_fails_closed():
    with pytest.raises(ValueError): build_demo_chat_orchestrator(Path("."), {"DEMO_CHAT_PROVIDER": "deepseek"})
    with pytest.raises(ValueError): build_demo_chat_orchestrator(Path("."), {"DEMO_CHAT_TIMEOUT_SECONDS": "0"})


def test_cors_origins_are_explicit_and_reject_wildcards():
    assert cors_origins("http://127.0.0.1:8502") == ["http://127.0.0.1:8502"]
    with pytest.raises(ValueError): cors_origins("*")
