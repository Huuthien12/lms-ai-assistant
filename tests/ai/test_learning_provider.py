from pathlib import Path

import pytest

from backend.services.ai.deeptutor_provider import DeepTutorProvider
from backend.services.ai.learning_provider import build_learning_generation_orchestrator
from backend.services.ai.ollama_provider import OllamaProvider


def test_learning_provider_defaults_to_existing_ollama_model():
    orchestrator=build_learning_generation_orchestrator(Path("DeepTutor"),{})
    assert isinstance(orchestrator.default_provider,OllamaProvider)
    assert orchestrator.default_provider.model=="qwen2.5:3b"


@pytest.mark.asyncio
async def test_groq_requires_explicit_selection_and_environment_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY",raising=False)
    orchestrator=build_learning_generation_orchestrator(Path("DeepTutor"),{
        "LEARNING_GENERATION_PROVIDER":"groq",
        "LEARNING_GENERATION_MODEL":"qwen/qwen3.8-27b",
    })
    assert isinstance(orchestrator.default_provider,DeepTutorProvider)
    result=await orchestrator.default_provider.generate(
        "document",response_format={"type":"json_object"})
    assert result.error_code=="PROVIDER_UNCONFIGURED"


def test_learning_provider_rejects_unknown_provider():
    with pytest.raises(ValueError,match="ollama or groq"):
        build_learning_generation_orchestrator(Path("DeepTutor"),{
            "LEARNING_GENERATION_PROVIDER":"unknown",
        })
