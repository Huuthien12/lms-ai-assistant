import logging
from typing import Optional, Dict, Any, List
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class GroundedChatService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("GroundedChatService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def chat(self, user_query: str, context_documents: List[str], system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        """Thực hiện sinh câu trả lời học tập thông minh dựa trên ngữ cảnh DeepTutor/KB."""
        
        if not context_documents or len(context_documents) == 0:
            # Xử lý trường hợp không có ngữ cảnh để chống hallucination
            return LLMResult(
                status="success",
                provider="grounded_chat_guard",
                model="guardrail",
                content="Xin lỗi, tôi không tìm thấy tài liệu hoặc ngữ cảnh phù hợp trong hệ thống để trả lời câu hỏi này.",
                latency_ms=0.0,
                error_code=None,
                fallback_used=False
            )

        formatted_context = "\n\n---\n\n".join(context_documents)
        
        default_system_prompt = (
            "Bạn là trợ lý AI học tập thông minh của hệ thống LMS. "
            "Hãy trả lời câu hỏi của học viên dựa TRỰC TIẾP vào các tài liệu ngữ cảnh được cung cấp bên dưới. "
            "Nếu thông tin không có trong ngữ cảnh, hãy thừa nhận bạn không biết và không bịa đặt thêm.\n\n"
            f"Ngữ cảnh tài liệu:\n{formatted_context}"
        )
        
        final_system_prompt = f"{system_prompt}\n\n{default_system_prompt}" if system_prompt else default_system_prompt

        return await self.orchestrator.generate(
            prompt=user_query,
            system_prompt=final_system_prompt,
            **kwargs
        )