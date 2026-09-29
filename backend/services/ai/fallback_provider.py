import logging
from typing import Optional, Any
from backend.services.ai.provider_base import LLMResult

try:
    from backend.services.ai.provider_base import BaseLLMProvider
except ImportError:
    try:
        from backend.services.ai.provider_base import LLMProvider as BaseLLMProvider
    except ImportError:
        class BaseLLMProvider:
            pass

logger = logging.getLogger(__name__)

class FallbackAIProvider(BaseLLMProvider):
    def __init__(self, primary_provider: Any, fallback_provider: Any):
        if not primary_provider or not fallback_provider:
            raise ValueError("FallbackAIProvider yêu cầu cả primary_provider và fallback_provider.")
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def health_check(self) -> bool:
        """Kiểm tra health status của fallback orchestrator dựa trên primary và fallback providers."""
        primary_healthy = True
        fallback_healthy = True

        if hasattr(self.primary_provider, "health_check"):
            try:
                primary_healthy = await self.primary_provider.health_check()
            except Exception:
                primary_healthy = False

        if hasattr(self.fallback_provider, "health_check"):
            try:
                fallback_healthy = await self.fallback_provider.health_check()
            except Exception:
                fallback_healthy = False

        return primary_healthy or fallback_healthy

    def _is_retryable_error(self, error_code: Optional[str]) -> bool:
        """Xác định lỗi có phải transient/retryable hay không theo đúng contract.

        QUAN TRỌNG: Không mặc định coi unknown/None là retryable. Fail-safe: unknown error -> NO fallback.
        """
        if not error_code:
            return False

        retryable_codes = {
            "HTTP_429",
            "HTTP_500",
            "HTTP_502",
            "HTTP_503",
            "HTTP_504",
            "TIMEOUT_OR_NETWORK_ERROR",
            "RATE_LIMIT",
            "SERVICE_UNAVAILABLE"
        }
        return error_code in retryable_codes

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        """Thực hiện generate với cơ chế fallback thông minh chỉ dựa trên lỗi retryable."""
        try:
            primary_result = await self.primary_provider.generate(prompt=prompt, system_prompt=system_prompt, **kwargs)

            # 1. Primary thành công -> Không gọi fallback
            if primary_result.status == "success":
                return primary_result

            # 2. Primary lỗi nhưng KHÔNG phải retryable -> Trả primary result, không gọi fallback
            if not self._is_retryable_error(primary_result.error_code):
                return primary_result

            # 3. Primary lỗi retryable -> Cố gắng gọi fallback provider
            logger.warning(f"Primary provider lỗi retryable ({primary_result.error_code}), đang chuyển sang fallback provider...")
            fallback_result = await self.fallback_provider.generate(prompt=prompt, system_prompt=system_prompt, **kwargs)

            if fallback_result.status == "success":
                fallback_result.fallback_used = True
                return fallback_result
            else:
                return fallback_result

        except Exception as e:
            logger.error(f"Lỗi ngoại lệ không mong muốn khi gọi primary provider: {str(e)}")
            raise e
