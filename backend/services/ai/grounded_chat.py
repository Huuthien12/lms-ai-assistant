import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

@dataclass
class RetrievedContextItem:
    text: str
    source_id: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class GroundedChatRequest:
    query: str
    contexts: List[RetrievedContextItem]
    course_id: Optional[str] = None
    kb_name: Optional[str] = None

@dataclass
class GroundedChatResponse:
    status: str
    answer: str
    course_id: Optional[str]
    kb_name: Optional[str]
    sources: List[Dict[str, Any]]
    ai: Dict[str, Any]

class GroundedChatService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("GroundedChatService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def chat(self, request: GroundedChatRequest, **kwargs: Any) -> GroundedChatResponse:
        """Thực hiện grounded chat dựa hoàn toàn vào context được cung cấp từ bên ngoài (DeepTutor/application layer)."""
        if not request or not request.contexts:
            # Empty context -> Trả về safe response ngay lập tức, KHÔNG gọi AI provider
            safe_result = LLMResult(
                status="success",
                provider="safe-fallback",
                model="local-safe",
                content="Xin lỗi, tôi không tìm thấy tài liệu hoặc ngữ cảnh phù hợp từ hệ thống để trả lời câu hỏi này.",
                latency_ms=0.0,
                error_code=None,
                fallback_used=True
            )
            return GroundedChatResponse(
                status=safe_result.status,
                answer=safe_result.content,
                course_id=request.course_id,
                kb_name=request.kb_name,
                sources=[],
                ai={
                    "provider": safe_result.provider,
                    "model": safe_result.model,
                    "fallback_used": safe_result.fallback_used,
                },
            )

        # Xây dựng context text đồng thời bảo toàn metadata thực tế
        context_blocks = []
        sources_meta = []
        for idx, item in enumerate(request.contexts, 1):
            source_info = f"[Nguồn {idx}]"
            if item.title:
                source_info += f" Tiêu đề: {item.title}"
            if item.source_id:
                source_info += f" (ID: {item.source_id})"
            if item.url:
                source_info += f" [URL: {item.url}]"

            context_blocks.append(f"{source_info}\nNội dung: {item.text}")
            source = {
                key: value
                for key, value in {
                    "source_id": item.source_id,
                    "title": item.title,
                    "score": item.score,
                    "page": item.metadata.get("page"),
                }.items()
                if value is not None
            }
            sources_meta.append(source)

        combined_context = "\n\n".join(context_blocks)

        course_info = f"Course ID: {request.course_id}" if request.course_id else "Không xác định course_id"
        kb_info = f"Knowledge Base: {request.kb_name}" if request.kb_name else "Không xác định KB"

        system_prompt = (
            "Bạn là trợ lý AI học tập chuyên nghiệp. "
            "Nhiệm vụ của bạn là trả lời câu hỏi của học viên DỰA TRÊN VÀ CHỈ DỰA TRÊN ngữ cảnh được cung cấp bên dưới. "
            "TUYỆT ĐỐI KHÔNG tự bịa đặt thông tin, không tự chế nguồn (fabricated source) không có trong ngữ cảnh. "
            "Nếu thông tin không có trong ngữ cảnh, hãy thừa nhận là không biết."
        )

        prompt = (
            f"Thông tin bối cảnh:\n- {course_info}\n- {kb_info}\n\n"
            f"Các nguồn tài liệu được truy xuất:\n{combined_context}\n\n"
            f"Câu hỏi của học viên: {request.query}\n\n"
            "Hãy trả lời câu hỏi dựa trên các nguồn trên, kèm theo trích dẫn nguồn thực tế nếu có."
        )

        # Gọi LLM thông qua orchestrator
        result = await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )
        return GroundedChatResponse(
            status=result.status,
            answer=result.content if result.status == "success" else "",
            course_id=request.course_id,
            kb_name=request.kb_name,
            sources=sources_meta,
            ai={
                "provider": result.provider,
                "model": result.model,
                "fallback_used": result.fallback_used,
            },
        )
