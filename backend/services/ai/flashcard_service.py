import logging
from typing import Optional, Dict, Any
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class FlashcardService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("FlashcardService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def generate_flashcards(self, topic_or_text: str, count: int = 5, **kwargs: Any) -> LLMResult:
        """Tạo danh sách các flashcard (mặt trước / mặt sau) từ nội dung hoặc chủ đề học tập."""
        if not topic_or_text:
            raise ValueError("topic_or_text không được để trống.")

        system_prompt = (
            "Bạn là trợ lý AI chuyên thiết kế học liệu flashcard cho hệ thống LMS. "
            "Hãy trả về kết quả dưới định dạng JSON hợp lệ bao gồm danh sách các flashcard. "
            "Mỗi flashcard phải có khóa 'front' (thuật ngữ hoặc câu hỏi ngắn gọn) và 'back' (định nghĩa hoặc câu trả lời chi tiết)."
        )

        prompt = (
            f"Hãy tạo {count} flashcard ôn tập chất lượng cao dựa trên nội dung/chủ đề sau: '{topic_or_text}'. "
            "Đảm bảo đầu ra là định dạng JSON có khóa 'flashcards' chứa danh sách các thẻ."
        )

        return await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )