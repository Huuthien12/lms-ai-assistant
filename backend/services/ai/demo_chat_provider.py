"""Post-experiment demo chat provider selection; never changes benchmark config."""
from collections.abc import Mapping
from pathlib import Path

from backend.services.ai.deeptutor_provider import DeepTutorProvider
from backend.services.ai.fallback_provider import FallbackAIProvider
from backend.services.ai.model_config import ModelConfig
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator


def build_demo_chat_orchestrator(deeptutor_dir: Path, settings: Mapping[str, str]) -> AIOrchestrator:
    provider = (settings.get("DEMO_CHAT_PROVIDER") or "ollama").strip().lower()
    timeout = float((settings.get("DEMO_CHAT_TIMEOUT_SECONDS") or "60").strip())
    if timeout <= 0:
        raise ValueError("DEMO_CHAT_TIMEOUT_SECONDS must be positive")
    ollama = OllamaProvider(
        model=(settings.get("OLLAMA_MODEL") or "qwen2.5:3b").strip(),
        base_url=(settings.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip(),
        timeout_seconds=timeout,
    )
    if provider == "ollama":
        return AIOrchestrator(ollama)
    if provider != "groq":
        raise ValueError("DEMO_CHAT_PROVIDER must be ollama or groq")
    groq = DeepTutorProvider(ModelConfig(
        provider="groq", model=(settings.get("DEMO_CHAT_MODEL") or "qwen/qwen3.8-27b").strip(),
        timeout_seconds=timeout, api_key_env="GROQ_API_KEY", allow_cloud_document_content=True,
    ), deeptutor_dir)
    fallback = (settings.get("DEMO_CHAT_FALLBACK") or "ollama").strip().lower()
    if fallback == "ollama":
        return AIOrchestrator(FallbackAIProvider(groq, ollama))
    if fallback in {"", "none"}:
        return AIOrchestrator(groq)
    raise ValueError("DEMO_CHAT_FALLBACK must be ollama or none")
