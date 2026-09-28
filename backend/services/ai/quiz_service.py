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

    async def generate_quiz(self, topic: str, num_questions: int = 3, difficulty: str = "medium", client_facing: bool = False, **kwargs: Any) -> LLMResult:
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

        result = await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )

        if result.status != "success":
            return result

        # Thực hiện structured validation và xử lý client-facing boundary nếu cần
        try:
            # Parse nội dung để validate JSON và schema cơ bản
            parsed_content = json.loads(result.content)
            
            if not isinstance(parsed_content, dict) or "questions" not in parsed_content:
                # Thử cố gắng parse linh hoạt nếu LLM trả về list hoặc dạng khác
                if isinstance(parsed_content, list):
                    parsed_content = {"questions": parsed_content}
                else:
                    raise ValueError("JSON không đúng cấu trúc schema yêu cầu (thiếu khóa 'questions').")

            questions = parsed_content.get("questions", [])
            if not isinstance(questions, list) or len(questions) == 0:
                raise ValueError("Danh sách câu hỏi trống hoặc không hợp lệ.")

            validated_questions = []
            for q in questions:
                if not isinstance(q, dict) or "question" not in q or "options" not in q:
                    continue
                
                # Copy câu hỏi để tránh ảnh hưởng dữ liệu gốc
                clean_q = dict(q)
                
                # Nếu phục vụ client-facing trước khi submit, ẩn đáp án và giải thích
                if client_facing:
                    clean_q.pop("correct_answer", None)
                    clean_q.pop("explanation", None)
                
                validated_questions.append(clean_q)

            if len(validated_questions) == 0:
                raise ValueError("Không có câu hỏi nào vượt qua bước validation schema.")

            parsed_content["questions"] = validated_questions
            result.content = json.dumps(parsed_content, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Quiz validation lỗi: {str(e)}")
            return LLMResult(
                status="error",
                provider=result.provider,
                model=result.model,
                content=f"Lỗi cấu trúc dữ liệu Quiz: {str(e)}",
                latency_ms=result.latency_ms,
                error_code="INVALID_QUIZ_SCHEMA",
                fallback_used=result.fallback_used
            )

        return result