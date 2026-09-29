import json
import logging
from typing import Dict, Any, List, Optional
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class QuizService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("QuizService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    def validate_and_parse_quiz(self, raw_content: str) -> Dict[str, Any]:
        """Validate và parse cấu trúc quiz từ raw content của LLM hoặc input."""
        try:
            if isinstance(raw_content, dict):
                data = raw_content
            else:
                # Cố gắng parse JSON, hỗ trợ trường hợp bọc trong markdown code block
                cleaned = raw_content.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                data = json.loads(cleaned.strip())
        except Exception as e:
            raise ValueError(f"INVALID_QUIZ_SCHEMA: Không thể parse JSON từ raw content: {str(e)}")

        if not isinstance(data, dict) or "questions" not in data:
            raise ValueError("INVALID_QUIZ_SCHEMA: Dữ liệu quiz phải là dictionary và chứa khóa 'questions'.")

        questions = data.get("questions")
        if not isinstance(questions, list) or len(questions) == 0:
            raise ValueError("INVALID_QUIZ_SCHEMA: Khóa 'questions' phải là một list không rỗng.")

        validated_questions = []
        for q in questions:
            if not isinstance(q, dict):
                raise ValueError("INVALID_QUIZ_SCHEMA: Mỗi question phải là một dictionary.")

            # 1. Validate question text
            q_text = q.get("question") or q.get("question_text")
            if not q_text or not isinstance(q_text, str) or not q_text.strip():
                raise ValueError("INVALID_QUIZ_SCHEMA: question text không được rỗng và phải là chuỗi.")

            # 2. Validate type (chỉ hỗ trợ 'mcq')
            q_type = q.get("type", "mcq")
            if q_type not in ["mcq"]:
                raise ValueError(f"INVALID_QUIZ_SCHEMA: Loại câu hỏi không hỗ trợ: {q_type}")

            # 3. Validate options
            options = q.get("options")
            if not isinstance(options, list) or len(options) == 0:
                raise ValueError("INVALID_QUIZ_SCHEMA: Options phải là một list không rỗng.")

            opt_ids = set()
            for opt in options:
                if not isinstance(opt, dict):
                    raise ValueError("INVALID_QUIZ_SCHEMA: Mỗi option phải là một dictionary.")
                opt_id = opt.get("id")
                opt_text = opt.get("text")
                if not opt_id or not isinstance(opt_id, str) or not opt_id.strip():
                    raise ValueError("INVALID_QUIZ_SCHEMA: Option ID không được rỗng.")
                if not opt_text or not isinstance(opt_text, str) or not opt_text.strip():
                    raise ValueError("INVALID_QUIZ_SCHEMA: Option text không được rỗng.")

                if opt_id in opt_ids:
                    raise ValueError(f"INVALID_QUIZ_SCHEMA: Duplicate option ID: {opt_id}")
                opt_ids.add(opt_id)

            # 4. Validate internal generated representation (correct answer/correct_option_id)
            correct_id = q.get("correct_option_id") or q.get("correct_answer")
            if not correct_id or (correct_id not in opt_ids):
                raise ValueError("INVALID_QUIZ_SCHEMA: correct_option_id/correct_answer bắt buộc phải tồn tại và trỏ tới option ID hợp lệ.")

            validated_q = {
                "question": q_text.strip(),
                "type": q_type,
                "options": [{"id": opt["id"].strip(), "text": opt["text"].strip()} for opt in options],
                "correct_option_id": correct_id,
                "explanation": q.get("explanation", "")
            }
            if "source_metadata" in q and q["source_metadata"]:
                validated_q["source_metadata"] = q["source_metadata"]

            validated_questions.append(validated_q)

        return {"questions": validated_questions}

    async def generate_quiz(self, prompt_text: str, client_facing: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Tạo quiz thông qua LLM orchestrator, validate schema và lọc bỏ thông tin nhạy cảm nếu client_facing=True."""
        system_prompt = (
            "Bạn là trợ lý AI chuyên tạo câu hỏi trắc nghiệm (mcq) cho LMS. "
            "Hãy trả về kết quả dưới dạng JSON hợp lệ tuân thủ schema gồm danh sách các câu hỏi, "
            "mỗi câu có 'question', 'type' ('mcq'), 'options' (list gồm 'id' và 'text'), "
            "'correct_option_id' và 'explanation'."
        )

        try:
            llm_result = await self.orchestrator.generate(
                prompt=prompt_text,
                system_prompt=system_prompt,
                **kwargs
            )

            if llm_result.status != "success":
                raise ValueError(f"LLM generation failed: {llm_result.error_code}")

            parsed_data = self.validate_and_parse_quiz(llm_result.content)
        except Exception as e:
            if "INVALID_QUIZ_SCHEMA" in str(e):
                raise e
            raise ValueError(f"INVALID_QUIZ_SCHEMA: {str(e)}")

        # 7. Nếu client_facing=True, loại bỏ hoàn toàn các trường nhạy cảm
        if client_facing:
            sanitized_questions = []
            for q in parsed_data["questions"]:
                sanitized_q = {
                    "question": q["question"],
                    "type": q["type"],
                    "options": q["options"]
                }
                if "source_metadata" in q:
                    sanitized_q["source_metadata"] = q["source_metadata"]
                sanitized_questions.append(sanitized_q)
            return {"questions": sanitized_questions}

        return parsed_data
