import logging
import json
from typing import Optional, Dict, Any, List
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class QuizGenerationService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("QuizGenerationService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def generate_quiz(self, topic: str, num_questions: int = 3, difficulty: str = "medium", **kwargs: Any) -> LLMResult:
        """Tạo các câu hỏi trắc nghiệm dựa trên chủ đề, số lượng và độ khó được yêu cầu."""
        if not topic:
            raise ValueError("Chủ đề (topic) không được để trống.")

        system_prompt = (
            "Bạn là trợ lý AI chuyên tạo câu hỏi kiểm tra đánh giá năng lực học tập cho hệ thống LMS. "
            "Hãy trả về kết quả dưới định dạng JSON hợp lệ bao gồm danh sách các câu hỏi trắc nghiệm. "
            "Mỗi câu hỏi phải bao gồm: question, options (danh sách 4 lựa chọn A, B, C, D), correct_answer và explanation."
        )

        prompt = (
            f"Hãy tạo cho tôi {num_questions} câu hỏi trắc nghiệm về chủ đề: '{topic}' "
            f"với mức độ khó là '{difficulty}'. "
            "Đảm bảo định dạng đầu ra là một đối tượng JSON có khóa 'questions' chứa danh sách câu hỏi."
        )

        return await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )