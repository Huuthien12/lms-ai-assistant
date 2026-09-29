import logging
from typing import Optional, Dict, Any, List
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

logger = logging.getLogger(__name__)

class RecommendationService:
    def __init__(self, orchestrator: AIOrchestrator):
        if not orchestrator:
            raise ValueError("RecommendationService yêu cầu AIOrchestrator.")
        self.orchestrator = orchestrator

    def _evaluate_rule_first(self, mastery_data: Dict[str, Any], deadline: Optional[str] = None) -> Dict[str, Any]:
        """Thực hiện đánh giá recommendation theo rule-first deterministic dựa trên TopicMastery chuẩn."""
        score = mastery_data.get("mastery_score", 0.0)
        evidence_count = mastery_data.get("evidence_count", 0)
        confidence_level = mastery_data.get("confidence_level", "MEDIUM")
        topic = mastery_data.get("topic", "General")

        # Kiểm tra điều kiện insufficient evidence
        insufficient_evidence = evidence_count < 2 or confidence_level == "LOW"

        actions = []
        if insufficient_evidence:
            actions = ["REVIEW_TOPIC", "EASY_QUIZ"]
            status_note = "INSUFFICIENT_EVIDENCE"
        else:
            if score < 50.0:
                actions = ["REVIEW_TOPIC", "GENERATE_FLASHCARDS", "EASY_QUIZ"]
                status_note = "WEAK"
            elif 50.0 <= score <= 69.0:
                actions = ["REVIEW_TOPIC", "MEDIUM_QUIZ"]
                status_note = "DEVELOPING"
            elif 70.0 <= score <= 84.0:
                actions = ["MEDIUM_QUIZ", "HARD_QUIZ"]
                status_note = "PROFICIENT"
            else: # >= 85.0
                actions = ["CONTINUE_NEXT_TOPIC", "HARD_QUIZ"]
                status_note = "MASTERED"

        rule_result = {
            "topic": topic,
            "mastery_score": score,
            "status_note": status_note,
            "insufficient_evidence": insufficient_evidence,
            "recommended_actions": actions,
            "deadline": deadline if deadline else None
        }
        return rule_result

    async def get_recommendations(self, topic_mastery: Dict[str, Any], available_courses_or_topics: List[str], deadline: Optional[str] = None, **kwargs: Any) -> LLMResult:
        """Đưa ra gợi ý học tập cá nhân hóa dựa trên TopicMastery tuân thủ rule-first deterministic."""
        if not topic_mastery:
            raise ValueError("topic_mastery không được để trống.")

        # 1. Tính toán deterministic recommendation trước khi gọi LLM
        deterministic_rec = self._evaluate_rule_first(topic_mastery, deadline)

        system_prompt = (
            "Bạn là trợ lý AI chuyên gia vấn học tập và cá nhân hóa lộ trình cho hệ thống LMS. "
            "Nhiệm vụ của bạn chỉ là diễn đạt và giải thích kết quả đề xuất học tập đã được tính toán sẵn theo quy tắc deterministic. "
            "TUYỆT ĐỐI KHÔNG tự bịa đặt điểm số mastery, không tự thay đổi hành động đề xuất, không bịa đặt deadline hoặc dữ liệu mới."
        )

        deadline_str = f"Deadline thực tế: {deadline}" if deadline else "Không có deadline cụ thể được thiết lập."
        prompt = (
            f"Thông tin TopicMastery chuẩn: {topic_mastery}\n"
            f"Kết quả phân tích rule-first: {deterministic_rec}\n"
            f"Danh sách chủ đề/khóa học khả dụng: {available_courses_or_topics}\n"
            f"{deadline_str}\n\n"
            "Hãy viết lời giải thích rõ ràng, ngắn gọn và khích lệ dựa trên các hành động đề xuất ở trên."
        )

        try:
            llm_result = await self.orchestrator.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                **kwargs
            )
            if llm_result.status != "success":
                # Nếu LLM lỗi, vẫn trả về kết quả rule-based thông qua LLMResult thành công chứa rule data
                return LLMResult(
                    status="success",
                    provider=llm_result.provider,
                    model=llm_result.model,
                    content=str(deterministic_rec),
                    latency_ms=llm_result.latency_ms,
                    error_code=None,
                    fallback_used=llm_result.fallback_used
                )

            # Gắn kèm rule_recommendation vào kết quả trả về nếu cần thiết hoặc giữ nguyên content LLM
            return llm_result
        except Exception as e:
            logger.warning(f"LLM call thất bại trong RecommendationService, trả về rule-based fallback: {str(e)}")
            return LLMResult(
                status="success",
                provider="rule-engine-fallback",
                model="local-rule",
                content=str(deterministic_rec),
                latency_ms=0.0,
                error_code=None,
                fallback_used=True
            )
