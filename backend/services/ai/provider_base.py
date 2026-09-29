from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

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