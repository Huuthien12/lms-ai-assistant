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
        """Thực hiện sinh câu trả lời dựa trên truy vấn của người dùng và các tài liệu ngữ cảnh được cung cấp."""
        if not user_query:
            raise ValueError("Truy vấn của người dùng (user_query) không được để trống.")
        
        # Chuẩn hóa context từ danh sách tài liệu
        formatted_context = "\n\n".join([f"- {doc}" for doc in context_documents]) if context_documents else "Không có tài liệu ngữ cảnh cụ thể."
        
        default_system_prompt = (
            "Bạn là trợ lý AI học tập thông minh cho hệ thống LMS. "
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