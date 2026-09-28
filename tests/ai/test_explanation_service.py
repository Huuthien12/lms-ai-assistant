import pytest
from unittest.mock import AsyncMock
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.explanation_service import ExplanationService

@pytest.mark.asyncio
async def test_explanation_service_success():
    mock_orchestrator = AsyncMock(spec=AIOrchestrator)
    mock_orchestrator.generate.return_value = LLMResult(
        status="success",
        provider="deepseek",
        model="chat",
        content="Đáp án của bạn chưa đúng vì lý do X...",
        latency_ms=110
    )

    explanation_service = ExplanationService(orchestrator=mock_orchestrator)
    result = await explanation_service.explain_wrong_answer(
        question="2 + 2 = ?",
        student_answer="5",
        correct_answer="4",
        explanation="Phép cộng cơ bản"
    )

    assert result.status == "success"
    assert "chưa đúng" in result.content
    mock_orchestrator.generate.assert_awaited_once()