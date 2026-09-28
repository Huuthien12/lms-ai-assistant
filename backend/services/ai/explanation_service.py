import logging
from typing import Optional, Dict, Any, List
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class ExplanationService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("ExplanationService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def explain_wrong_answer(
        self, 
        question: str, 
        student_answer: str, 
        correct_answer: str, 
        explanation: Optional[str] = None, 
        context_documents: Optional[List[str]] = None,
        **kwargs: Any
    ) -> LLMResult:
        """Phân tích lý do tại sao học viên chọn sai và đưa ra gợi ý ôn tập cho hệ thống LMS dựa trên ngữ cảnh."""
        
        system_prompt = (
            "Bạn là trợ lý AI chuyên phân tích lỗi sai và hướng dẫn học tập cho hệ thống LMS. "
            "Nhiệm vụ của bạn là giải thích cho học viên biết tại sao đáp án của họ chưa chính xác, "
            "phân tích điểm khác biệt với đáp án đúng, và đưa ra gợi ý ôn tập mang tính xây dựng, không chê bai. "
            "Nếu có tài liệu ngữ cảnh được cung cấp, hãy bám sát vào ngữ cảnh đó và không bịa đặt nguồn."
        )

        context_section = ""
        if context_documents and len(context_documents) > 0:
            formatted_context = "\n\n---\n\n".join(context_documents)
            context_section = f"\n\nNgữ cảnh tài liệu tham khảo:\n{formatted_context}"

        prompt = (
            f"Câu hỏi: {question}\n"
            f"Đáp án học viên đã chọn: {student_answer}\n"
            f"Đáp án đúng thực tế: {correct_answer}\n"
            f"Giải thích gốc (nếu có): {explanation or 'Không có'}"
            f"{context_section}\n\n"
            "Hãy viết lời giải thích rõ ràng, dễ hiểu giúp học viên hiểu bản chất vấn đề và không lặp lại lỗi sai."
        )

        return await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )