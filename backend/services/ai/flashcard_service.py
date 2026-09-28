import logging
import json
from typing import Optional, Dict, Any, List
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class FlashcardService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("FlashcardService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    async def generate_flashcards(self, topic_or_text: str, count: int = 5, difficulty: str = "medium", **kwargs: Any) -> LLMResult:
        """Tạo danh sách các flashcard (mặt trước / mặt sau) từ nội dung hoặc chủ đề học tập với structured validation."""
        if not topic_or_text:
            raise ValueError("topic_or_text không được để trống.")

        system_prompt = (
            "Bạn là trợ lý AI chuyên thiết kế học liệu flashcard cho hệ thống LMS. "
            "Hãy trả về kết quả dưới định dạng JSON hợp lệ bao gồm danh sách các flashcard. "
            "Mỗi flashcard phải có khóa 'front' (thuật ngữ hoặc câu hỏi ngắn gọn), 'back' (định nghĩa hoặc câu trả lời), "
            "và 'difficulty' (độ khó tương ứng)."
        )

        prompt = (
            f"Hãy tạo {count} flashcard ôn tập về nội dung hoặc chủ đề sau: '{topic_or_text}' "
            f"với mức độ khó '{difficulty}'. "
            "Đảm bảo đầu ra là định dạng JSON có khóa 'flashcards' chứa danh sách các thẻ."
        )

        result = await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )

        if result.status != "success":
            return result

        # Thực hiện structured validation cho flashcards
        try:
            parsed_content = json.loads(result.content)
            
            if not isinstance(parsed_content, dict) or "flashcards" not in parsed_content:
                if isinstance(parsed_content, list):
                    parsed_content = {"flashcards": parsed_content}
                else:
                    raise ValueError("JSON không đúng schema flashcards.")

            cards = parsed_content.get("flashcards", [])
            if not isinstance(cards, list):
                raise ValueError("Khóa 'flashcards' phải là một danh sách.")

            validated_cards = []
            for card in cards:
                if not isinstance(card, dict) or "front" not in card or "back" not in card:
                    continue
                validated_cards.append({
                    "front": str(card.get("front", "")).strip(),
                    "back": str(card.get("back", "")).strip(),
                    "difficulty": card.get("difficulty", difficulty)
                })

            if len(validated_cards) == 0:
                raise ValueError("Không có flashcard nào hợp lệ sau khi validate.")

            parsed_content["flashcards"] = validated_cards
            result.content = json.dumps(parsed_content, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Flashcard validation lỗi: {str(e)}")
            return LLMResult(
                status="error",
                provider=result.provider,
                model=result.model,
                content=f"Lỗi cấu trúc dữ liệu Flashcard: {str(e)}",
                latency_ms=result.latency_ms,
                error_code="INVALID_FLASHCARD_SCHEMA",
                fallback_used=result.fallback_used
            )

        return result