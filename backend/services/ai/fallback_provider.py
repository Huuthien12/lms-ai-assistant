import logging
import time
from typing import Optional, Dict, Any
from backend.services.ai.provider_base import LLMProvider, LLMResult

logger = logging.getLogger(__name__)

class FallbackLLMProvider(LLMProvider):
    def __init__(self, primary_provider: LLMProvider, fallback_provider: LLMProvider):
        if not primary_provider or not fallback_provider:
            raise ValueError("Cả primary provider và fallback provider bắt buộc phải được cung cấp.")
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    def _is_retryable_error(self, error_code: Optional[str]) -> bool:
        if not error_code:
            return True  # Nếu không có mã lỗi cụ thể nhưng status là error thì cho phép fallback an toàn
        
        retryable_codes = {"429", "500", "502", "503", "504", "timeout", "rate_limit", "unavailable"}
        code_str = str(error_code).lower()
        return any(rc in code_str for rc in retryable_codes)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        start_time = time.time()
        
        primary_result = await self.primary_provider.generate(prompt, system_prompt, **kwargs)
        
        if primary_result.status == "success":
            return primary_result
            
        # Kiểm tra xem lỗi có phải retryable không trước khi quyết định fallback
        if not self._is_retryable_error(primary_result.error_code):
            logger.warning(f"Primary provider gặp lỗi non-retryable ({primary_result.error_code}). Không thực hiện fallback.")
            return primary_result

        logger.warning(f"Primary provider thất bại với error_code={primary_result.error_code}. Tiến hành chuyển sang Fallback provider.")
        
        fallback_result = await self.fallback_provider.generate(prompt, system_prompt, **kwargs)
        
        if fallback_result.status == "success":
            fallback_result.fallback_used = True
            return fallback_result
            
        return fallback_result

    async def health_check(self) -> Dict[str, Any]:
        primary_health = await self.primary_provider.health_check()
        fallback_health = await self.fallback_provider.health_check()
        return {
            "primary": primary_health,
            "fallback": fallback_health,
            "status": "healthy" if primary_health.get("status") == "healthy" or fallback_health.get("status") == "healthy" else "unhealthy"
        }