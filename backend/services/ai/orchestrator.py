import logging
from typing import Optional, Dict, Any
from backend.services.ai.provider_base import LLMProvider, LLMResult

logger = logging.getLogger(__name__)

class AIOrchestrator:
    def __init__(self, default_provider: LLMProvider):
        if not default_provider:
            raise ValueError("AIOrchestrator yêu cầu ít nhất một default_provider.")
        self.default_provider = default_provider

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        """Thực hiện gọi sinh nội dung thông qua provider mặc định (có thể là FallbackLLMProvider)."""
        try:
            return await self.default_provider.generate(prompt, system_prompt, **kwargs)
        except Exception as e:
            logger.error(f"Lỗi không xử lý được trong AIOrchestrator: {str(e)}")
            raise

    async def health_check(self) -> Dict[str, Any]:
        """Kiểm tra sức khỏe của toàn bộ chuỗi provider."""
        return await self.default_provider.health_check()