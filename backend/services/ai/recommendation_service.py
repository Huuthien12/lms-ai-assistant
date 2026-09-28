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

    async def get_recommendations(self, student_profile: Dict[str, Any], available_courses_or_topics: List[str], **kwargs: Any) -> LLMResult:
        """Đưa ra gợi ý lộ trình hoặc tài liệu học tập cá nhân hóa dựa trên hồ sơ và năng lực học viên."""
        if not student_profile:
            raise ValueError("student_profile không được để trống.")

        system_prompt = (
            "Bạn là trợ lý AI chuyên gia vấn học tập và cá nhân hóa lộ trình cho hệ thống LMS. "
            "Hãy phân tích hồ sơ năng lực của học viên và danh sách tài liệu/chủ đề hiện có để đưa ra các gợi ý học tập "
            "phù hợp nhất, giúp khắc phục điểm yếu và phát huy điểm mạnh."
        )

        prompt = (
            f"Hồ sơ học viên: {student_profile}\n"
            f"Danh sách chủ đề/khóa học khả dụng: {available_courses_or_topics}\n\n"
            "Hãy đưa ra đề xuất học tập cụ thể, cá nhân hóa kèm theo lý do giải thích rõ ràng dưới dạng cấu trúc gọn gàng."
        )

        return await self.orchestrator.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )