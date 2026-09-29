import json
import logging
from typing import Dict, Any, List, Optional
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class FlashcardService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("FlashcardService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    def validate_and_parse_flashcards(self, raw_content: str) -> Dict[str, Any]:
        """Validate và parse cấu trúc flashcards từ raw content của LLM."""
        try:
            if isinstance(raw_content, dict):
                data = raw_content
            else:
                cleaned = raw_content.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                data = json.loads(cleaned.strip())
        except Exception as e:
            raise ValueError(f"INVALID_FLASHCARD_SCHEMA: Không thể parse JSON: {str(e)}")

        if not isinstance(data, dict) or "flashcards" not in data:
            raise ValueError("INVALID_FLASHCARD_SCHEMA: Dữ liệu phải chứa khóa 'flashcards'.")

        cards = data.get("flashcards")
        if not isinstance(cards, list) or len(cards) == 0:
            raise ValueError("INVALID_FLASHCARD_SCHEMA: Khóa 'flashcards' phải là list không rỗng.")

        validated_cards = []
        for card in cards:
            if not isinstance(card, dict):
                raise ValueError("INVALID_FLASHCARD_SCHEMA: Mỗi flashcard phải là một dictionary.")

            front = card.get("front_text") or card.get("front")
            back = card.get("back_text") or card.get("back")

            if not front or not isinstance(front, str) or not front.strip():
                raise ValueError("INVALID_FLASHCARD_SCHEMA: front_text không được rỗng.")
            if not back or not isinstance(back, str) or not back.strip():
                raise ValueError("INVALID_FLASHCARD_SCHEMA: back_text không được rỗng.")

            validated_card = {
                "front_text": front.strip(),
                "back_text": back.strip(),
                "topic": card.get("topic", "General"),
                "difficulty": card.get("difficulty", "medium")
            }
            if "source_metadata" in card and card["source_metadata"]:
                validated_card["source_metadata"] = card["source_metadata"]

            validated_cards.append(validated_card)

        return {"flashcards": validated_cards}

    async def generate_flashcards(self, prompt_text: str, source_metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """Tạo flashcards thông qua LLM orchestrator, validate schema và bảo toàn source_metadata thực tế."""
        system_prompt = (
            "Bạn là trợ lý AI chuyên tạo flashcard học tập cho LMS. "
            "Hãy trả về kết quả JSON hợp lệ chứa danh sách flashcards gồm front_text, back_text, topic, difficulty."
        )

        try:
            llm_result = await self.orchestrator.generate(
                prompt=prompt_text,
                system_prompt=system_prompt,
                **kwargs
            )

            if llm_result.status != "success":
                raise ValueError(f"LLM generation failed: {llm_result.error_code}")

            parsed_data = self.validate_and_parse_flashcards(llm_result.content)
        except Exception as e:
            if "INVALID_FLASHCARD_SCHEMA" in str(e):
                raise e
            raise ValueError(f"INVALID_FLASHCARD_SCHEMA: {str(e)}")

        if source_metadata:
            for card in parsed_data["flashcards"]:
                if "source_metadata" not in card:
                    card["source_metadata"] = source_metadata

        return parsed_data
