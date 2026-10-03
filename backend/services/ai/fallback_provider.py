from dataclasses import replace
from typing import Optional, Any, Dict

from backend.services.ai.provider_base import (
    LLMProvider, LLMResult, provider_error, safe_result, safe_health,
)


class FallbackAIProvider(LLMProvider):
    provider = "fallback"
    model = "provider-chain"

    def __init__(self, primary_provider: Any, fallback_provider: Any):
        if not primary_provider or not fallback_provider:
            raise ValueError("FallbackAIProvider requires primary and fallback providers")
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def health_check(self) -> Dict[str, Any]:
        primary = await safe_health(self.primary_provider)
        fallback = await safe_health(self.fallback_provider)
        statuses = (primary["status"], fallback["status"])
        status = ("available" if "available" in statuses else
                  "unconfigured" if all(s == "unconfigured" for s in statuses) else "unavailable")
        return {"provider": self.provider, "model": self.model, "status": status,
                "primary": primary, "fallback": fallback}

    def _is_retryable_error(self, error_code: Optional[str]) -> bool:
        return isinstance(error_code, str) and error_code in {
            "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504",
            "TIMEOUT_OR_NETWORK_ERROR", "RATE_LIMIT", "SERVICE_UNAVAILABLE",
        }

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        try:
            primary = await self.primary_provider.generate(
                prompt=prompt, system_prompt=system_prompt, **kwargs)
            primary = safe_result(primary)
        except Exception:
            return provider_error(self.primary_provider)
        if primary.status == "success" or not self._is_retryable_error(primary.error_code):
            return primary
        try:
            fallback = safe_result(await self.fallback_provider.generate(
                prompt=prompt, system_prompt=system_prompt, **kwargs))
        except Exception:
            fallback = provider_error(self.fallback_provider)
        return replace(fallback, fallback_used=True)
