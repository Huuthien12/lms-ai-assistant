import logging
import time
from typing import Optional, Dict, Any
from backend.services.ai.provider_base import LLMProvider, LLMResult

logger = logging.getLogger(__name__)

class FallbackLLMProvider(LLMProvider):
    def __init__(self, primary_provider: LLMProvider, fallback_provider: LLMProvider):
        if not primary_provider or not fallback_provider:
            raise ValueError("Cả primary_provider và fallback_provider đều bắt buộc phải được cung cấp.")
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        start_time = time.time()
        
        # Thử gọi Provider chính trước
        primary_result = await self.primary_provider.generate(prompt, system_prompt, **kwargs)
        
        if primary_result.status == "success":
            return primary_result
            
        logger.warning(f"Primary provider ({primary_result.provider}) thất bại với error_code={primary_result.error_code}. Tiến hành chuyển sang Fallback provider.")
        
        # Nếu Provider chính lỗi, chuyển sang gọi Provider dự phòng
        fallback_result = await self.fallback_provider.generate(prompt, system_prompt, **kwargs)
        
        if fallback_result.status == "success":
            # Đánh dấu cờ fallback_used = True theo đúng chuẩn contract
            fallback_result.fallback_used = True
            return fallback_result
            
        # Nếu cả 2 đều thất bại, trả về kết quả lỗi của fallback kèm tổng thời gian
        fallback_result.latency_ms = (time.time() - start_time) * 1000
        return fallback_result

    async def health_check(self) -> Dict[str, Any]:
        primary_health = await self.primary_provider.health_check()
        fallback_health = await self.fallback_provider.health_check()
        
        return {
            "orchestrator_mode": "fallback_wrapper",
            "primary": primary_health,
            "fallback": fallback_health
        }