from collections.abc import Mapping
from pathlib import Path

from backend.services.ai.deeptutor_provider import DeepTutorProvider
from backend.services.ai.model_config import ModelConfig
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator


def build_learning_generation_orchestrator(
    deeptutor_dir: Path, settings: Mapping[str, str],
) -> AIOrchestrator:
    provider=(settings.get("LEARNING_GENERATION_PROVIDER") or "ollama").strip().lower()
    timeout=float(settings.get("LEARNING_GENERATION_PROVIDER_TIMEOUT_SECONDS") or
                  settings.get("OLLAMA_TIMEOUT_SECONDS") or "120")
    model=(settings.get("LEARNING_GENERATION_MODEL") or "").strip()
    if provider=="ollama":
        return AIOrchestrator(OllamaProvider(
            model=model or (settings.get("OLLAMA_MODEL") or "qwen2.5:3b").strip(),
            base_url=(settings.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip(),
            timeout_seconds=timeout))
    if provider=="groq":
        config=ModelConfig(provider="groq",model=model or "qwen/qwen3.8-27b",
            timeout_seconds=timeout,api_key_env="GROQ_API_KEY",
            allow_cloud_document_content=True)
        return AIOrchestrator(DeepTutorProvider(config,deeptutor_dir))
    raise ValueError("LEARNING_GENERATION_PROVIDER must be ollama or groq")
