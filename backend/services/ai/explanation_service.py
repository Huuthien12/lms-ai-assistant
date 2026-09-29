import json
import logging
from typing import Dict, Any, Optional
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class ExplanationService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("ExplanationService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def generate_explanation(
        self,
        question: str,
        student_answer: str,
        correct_answer: str,
        context: Optional[str] = None,
        source_metadata: Optional[Any] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Tạo giải thích câu trả lời sai dựa trên context và source thật (không tự fabricate)."""
        prompt = f"Câu hỏi: {question}\nĐáp án của học sinh: {student_answer}\nĐáp án đúng: {correct_answer}"
        if context:
            prompt += f"\nContext/Tài liệu tham khảo thực tế:\n{context}"

        system_prompt = (
            "Bạn là trợ lý AI LMS hỗ trợ giải thích lý do sai sót cho học sinh một cách sư phạm. "
            "Trả về kết quả dưới dạng JSON chứa explanation và key_concept."
        )

        try:
            llm_result = await self.orchestrator.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                **kwargs
            )

            # Nếu orchestrator/provider lỗi, trả về failure đúng contract, không giả success
            if llm_result.status != "success":
                return {
                    "status": "error",
                    "error_code": llm_result.error_code or "LLM_GENERATION_FAILED",
                    "explanation": llm_result.content
                }

            content = llm_result.content
            try:
                cleaned = content.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                data = json.loads(cleaned.strip())
                explanation = data.get("explanation", content)
                key_concept = data.get("key_concept", "")
            except Exception:
                explanation = content
                key_concept = ""

            result = {
                "status": "success",
                "explanation": explanation,
                "key_concept": key_concept,
                "sources": []
            }

            # Preserve source metadata thật nếu có, không tự tạo source nếu không có input
            if source_metadata:
                if isinstance(source_metadata, list):
                    result["sources"] = source_metadata
                else:
                    result["sources"] = [source_metadata]

            return result

        except Exception as e:
            return {
                "status": "error",
                "error_code": "EXCEPTION",
                "explanation": str(e)
            }
