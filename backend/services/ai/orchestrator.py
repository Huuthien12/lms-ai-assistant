import os
from typing import Optional, Dict, Any, Mapping

from backend.services.ai.provider_base import LLMProvider, LLMResult, provider_error, safe_result, safe_health


class AIOrchestrator:
    def __init__(self, default_provider: LLMProvider):
        if not default_provider:
            raise ValueError("AIOrchestrator requires a default provider")
        self.default_provider = default_provider

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        try:
            return safe_result(await self.default_provider.generate(prompt, system_prompt, **kwargs))
        except Exception:
            return provider_error(self.default_provider)

    async def health_check(self) -> Dict[str, Any]:
        return await safe_health(self.default_provider)


def build_default_orchestrator(config: Optional[Mapping[str, str]] = None) -> AIOrchestrator:
    """Build from the supplied config, or environment when config is None.

    Building does not perform network calls. Blank settings use defaults.
    """
    from backend.services.ai.deepseek_provider import DeepSeekProvider
    from backend.services.ai.ollama_provider import OllamaProvider
    from backend.services.ai.fallback_provider import FallbackAIProvider

    settings = os.environ if config is None else config
    ollama = OllamaProvider(
        base_url=(settings.get("OLLAMA_BASE_URL") or "").strip() or "http://localhost:11434",
        model=(settings.get("OLLAMA_MODEL") or "").strip() or "qwen2.5:3b",
    )
    key = (settings.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return AIOrchestrator(FallbackAIProvider(DeepSeekProvider(key), ollama))
    return AIOrchestrator(ollama)
