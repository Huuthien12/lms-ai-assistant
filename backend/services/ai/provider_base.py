from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, replace

@dataclass
class LLMResult:
    status: str  # 'success' | 'error'
    provider: str
    model: str
    content: str
    latency_ms: float
    usage: Optional[Dict[str, int]] = field(default_factory=dict)
    error_code: Optional[str] = None
    fallback_used: bool = False

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        """Sinh nội dung từ prompt với cấu hình provider tương ứng."""
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Kiểm tra trạng thái khả dụng của provider."""
        pass


def provider_error(provider: Any) -> LLMResult:
    """Unexpected exceptions are non-retryable and contain no exception text."""
    name = getattr(provider, "provider", "unknown")
    model = getattr(provider, "model", "unknown")
    return LLMResult("error", name if isinstance(name, str) else "unknown",
                     model if isinstance(model, str) else "unknown", "", 0.0,
                     error_code="UNKNOWN_ERROR")


def safe_result(result: LLMResult) -> LLMResult:
    if result.status == "success":
        return result
    code = result.error_code
    known = {"TIMEOUT_OR_NETWORK_ERROR", "RATE_LIMIT", "SERVICE_UNAVAILABLE",
             "UNKNOWN_ERROR", "INVALID_RESPONSE", "MAX_RETRIES_EXCEEDED"}
    http_code = (isinstance(code, str) and len(code) == 8
                 and code.startswith("HTTP_") and code[5:].isdigit())
    return replace(result, content="", error_code=code if http_code or (
        isinstance(code, str) and code in known) else "UNKNOWN_ERROR", usage={})


async def safe_health(provider: Any) -> Dict[str, Any]:
    identity = provider_error(provider)
    result = {"provider": identity.provider, "model": identity.model, "status": "unavailable"}
    try:
        health = await provider.health_check()
        if isinstance(health, dict):
            if health.get("status") in ("available", "unavailable", "unconfigured"):
                result["status"] = health["status"]
            if getattr(provider, "provider", None) == "fallback":
                for key in ("primary", "fallback"):
                    child = health.get(key, {})
                    if isinstance(child, dict):
                        result[key] = {field: child[field] for field in
                                       ("provider", "model", "status") if field in child}
        elif health is True:
            result["status"] = "available"
    except Exception:
        pass
    return result
