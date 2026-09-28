import pytest
from unittest.mock import AsyncMock
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.recommendation_service import RecommendationService

@pytest.mark.asyncio
async def test_recommendation_service_success():
    mock_orchestrator = AsyncMock(spec=AIOrchestrator)
    mock_orchestrator.generate.return_value = LLMResult(
        status="success",
        provider="deepseek",
        model="chat",
        content="Dựa trên hồ sơ của bạn, chúng tôi đề xuất học khóa Python Advanced.",
        latency_ms=140
    )

    rec_service = RecommendationService(orchestrator=mock_orchestrator)
    profile = {"learning_style": "visual", "weak_topics": ["Recursion"]}
    topics = ["Python Advanced", "Data Structures"]
    
    result = await rec_service.get_recommendations(student_profile=profile, available_courses_or_topics=topics)

    assert result.status == "success"
    assert "đề xuất" in result.content
    mock_orchestrator.generate.assert_awaited_once()