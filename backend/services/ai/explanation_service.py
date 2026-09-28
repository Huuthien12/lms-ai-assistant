import logging
from typing import Optional, Dict, Any
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class ExplanationService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("ExplanationService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def explain_wrong_answer(self, question: str, student_answer: str, correct_answer: str, explanation: Optional[str] = None, **kwargs: Any) -> LLMResult:
        """Phân tích lý do tại sao học viên chọn sai và đưa ra lời giải thích chi tiết, mang tính sư phạm."""
        if not question or not student_answer or not correct_answer:
            raise ValueError("question, student_answer và correct_answer không được để trống.")

        system_prompt = (
            "Bạn là trợ lý AI gia sư thân thiện và am hiểu tâm lý học tập cho hệ thống LMS. "
            "Nhiệm vụ của bạn là giải thích cho học viên biết tại sao đáp án của họ chưa chính xác, "
            "phân tích điểm khác biệt với đáp án đúng, và đưa ra gợi ý ôn tập mang tính xây dựng, không chê bai."
        )

        prompt = (
            f"Câu hỏi: {question}\n"
            f"Đáp án học viên đã chọn: {student_answer}\n"
            f"Đáp án đúng thực tế: {correct_answer}\n"
            f"Giải thích gốc (nếu có): {explanation or 'Không có'}\n\n"
            "Hãy viết lời giải thích chi tiết, ngắn gọn, dễ hiểu giúp học viên hiểu bản chất vấn đề và không lặp lại lỗi sai."
        )

        return await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )